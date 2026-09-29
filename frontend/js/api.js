/*
 * api.js
 * ------
 * The one place the frontend talks to the backend.
 *
 * Every page loads this first. It holds the fetch wrapper, the login session,
 * the page guards that bounce you to login.html if you are not signed in, and
 * the small formatting helpers the pages share.
 */

(function (global) {
  "use strict";

  // The API is served from the same origin as these pages, so a relative base
  // works whether you open the site on localhost:8000 or deploy it anywhere.
  var BASE = "/api";

  var TOKEN_KEY = "ie_token";
  var USER_KEY = "ie_user";

  /* ------------------------------------------------------------ session */

  var session = {
    token: function () {
      try {
        return localStorage.getItem(TOKEN_KEY);
      } catch (e) {
        return null;
      }
    },

    user: function () {
      try {
        return JSON.parse(localStorage.getItem(USER_KEY) || "null");
      } catch (e) {
        return null;
      }
    },

    save: function (token, user) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    },

    update: function (user) {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    },

    clear: function () {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    },

    isLoggedIn: function () {
      return Boolean(session.token());
    }
  };

  /* ------------------------------------------------------------ requests */

  function headers(extra) {
    var h = extra || {};
    var token = session.token();
    if (token) {
      h.Authorization = "Bearer " + token;
    }
    return h;
  }

  function handle(response) {
    if (response.status === 401) {
      // The token has expired or was never valid. Start over.
      session.clear();
      if (!/login\.html|register\.html|index\.html/.test(location.pathname)) {
        location.href = "login.html?expired=1";
      }
      return Promise.reject(new Error("Your session has expired. Please log in again."));
    }

    return response.text().then(function (text) {
      var data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (e) {
          data = null;
        }
      }

      if (!response.ok) {
        var message = (data && (data.detail || data.message)) || "Something went wrong.";
        if (Array.isArray(message)) {
          // FastAPI validation errors come back as a list of objects.
          message = message
            .map(function (m) { return m.msg || JSON.stringify(m); })
            .join(", ");
        }
        var err = new Error(message);
        err.status = response.status;
        throw err;
      }
      return data;
    });
  }

  function request(method, path, body) {
    var options = { method: method, headers: headers({}) };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(BASE + path, options).then(handle);
  }

  var api = {
    get: function (path) { return request("GET", path); },
    post: function (path, body) { return request("POST", path, body || {}); },
    put: function (path, body) { return request("PUT", path, body || {}); },
    del: function (path) { return request("DELETE", path); },

    upload: function (path, formData) {
      return fetch(BASE + path, {
        method: "POST",
        headers: headers({}),
        body: formData
      }).then(handle);
    },

    login: function (identifier, password, role) {
      return request("POST", "/auth/login", {
        identifier: identifier,
        password: password,
        role: role || ""
      }).then(function (data) {
        session.save(data.token, data.user);
        return data;
      });
    },

    register: function (payload) {
      return request("POST", "/auth/register", payload).then(function (data) {
        session.save(data.token, data.user);
        return data;
      });
    },

    logout: function () {
      session.clear();
      location.href = "login.html";
    }
  };

  /* -------------------------------------------------------------- guards */

  /**
   * Call at the top of every page that needs a login. Returns the signed-in
   * user, or redirects and returns null. `role` optionally pins the page to
   * entrepreneurs or officers.
   */
  function requireLogin(role) {
    var user = session.user();
    if (!session.isLoggedIn() || !user) {
      location.href = "login.html";
      return null;
    }
    if (role && user.role !== role && user.role !== "admin") {
      // An officer landing on an applicant page (or the reverse) goes to the
      // dashboard that actually belongs to them.
      location.href = user.role === "officer" ? "officer-dashboard.html" : "dashboard.html";
      return null;
    }
    return user;
  }

  function homeFor(user) {
    return user && user.role === "officer" ? "officer-dashboard.html" : "dashboard.html";
  }

  /* ---------------------------------------------------------- formatting */

  var fmt = {
    /** 2000000 -> "₹20 Lakh", 80000000 -> "₹8 Crore" */
    money: function (value) {
      var n = Number(value || 0);
      if (!isFinite(n)) return "₹0";
      if (n >= 10000000) return "₹" + trim(n / 10000000) + " Crore";
      if (n >= 100000) return "₹" + trim(n / 100000) + " Lakh";
      return "₹" + n.toLocaleString("en-IN");
    },

    /** ISO date or datetime -> "16 September 2026" */
    date: function (value) {
      if (!value) return "—";
      var d = new Date(value);
      if (isNaN(d.getTime())) return String(value);
      return d.toLocaleDateString("en-IN", {
        day: "numeric", month: "long", year: "numeric"
      });
    },

    shortDate: function (value) {
      if (!value) return "—";
      var d = new Date(value);
      if (isNaN(d.getTime())) return String(value);
      return d.toLocaleDateString("en-IN", {
        day: "2-digit", month: "short", year: "numeric"
      });
    },

    /** "under_review" -> "Under Review" */
    label: function (value) {
      if (!value) return "";
      return String(value)
        .replace(/[_-]+/g, " ")
        .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    },

    /** Zero-pads the big counters on the dashboards: 4 -> "04" */
    pad: function (value) {
      var n = Number(value || 0);
      return n < 10 ? "0" + n : String(n);
    },

    /** Maps a backend status onto the CSS class the stylesheets already use. */
    statusClass: function (status) {
      switch (status) {
        case "approved":
        case "completed":
        case "verified":
        case "active":
          return "approved";
        case "rejected":
        case "expired":
        case "cancelled":
          return "rejected";
        case "query":
          return "query";
        default:
          return "pending";
      }
    }
  };

  function trim(n) {
    // 20.0 -> "20", 20.5 -> "20.5"
    return (Math.round(n * 100) / 100).toString();
  }

  /* ------------------------------------------------------------- helpers */

  /** Escapes anything that came from the API before it goes into innerHTML. */
  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function qs(name) {
    return new URLSearchParams(location.search).get(name);
  }

  function byId(id) {
    return document.getElementById(id);
  }

  /** Sets textContent if the element exists. Pages differ, so never assume. */
  function setText(id, value) {
    var el = byId(id);
    if (el) el.textContent = value;
    return el;
  }

  function setHTML(id, value) {
    var el = byId(id);
    if (el) el.innerHTML = value;
    return el;
  }

  /**
   * A small inline banner for errors and confirmations, so no page has to
   * fall back to alert(). Inserted at the top of <main> (or body).
   */
  function notify(message, type) {
    var existing = byId("ie-notice");
    if (existing) existing.remove();

    var box = document.createElement("div");
    box.id = "ie-notice";
    box.className = "ie-notice ie-notice-" + (type || "info");
    box.setAttribute("role", type === "error" ? "alert" : "status");
    box.textContent = message;

    var host = document.querySelector("main") || document.body;
    host.insertBefore(box, host.firstChild);
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });

    if (type !== "error") {
      setTimeout(function () {
        if (box.parentNode) box.remove();
      }, 5000);
    }
  }

  /** Renders a neutral "nothing here yet" block into a container. */
  function empty(container, message, actionHref, actionLabel) {
    if (!container) return;
    var action = actionHref
      ? '<a class="ie-empty-action" href="' + esc(actionHref) + '">' + esc(actionLabel || "Get started") + "</a>"
      : "";
    container.innerHTML =
      '<div class="ie-empty"><p>' + esc(message) + "</p>" + action + "</div>";
  }

  function loading(container, message) {
    if (!container) return;
    container.innerHTML =
      '<div class="ie-loading">' + esc(message || "Loading…") + "</div>";
  }

  /**
   * Wraps a page's setup in a single catch, so one failed request shows a
   * readable message instead of a silently blank page.
   */
  function boot(fn) {
    document.addEventListener("DOMContentLoaded", function () {
      wireCommonChrome();
      Promise.resolve()
        .then(fn)
        .catch(function (err) {
          console.error(err);
          notify(err.message || "Could not load this page.", "error");
        });
    });
  }

  /** Logout links and the signed-in user's name in the navbar. */
  function wireCommonChrome() {
    var links = document.querySelectorAll('a[href="login.html"]');
    Array.prototype.forEach.call(links, function (link) {
      if (link.textContent.trim().toLowerCase() === "logout") {
        link.addEventListener("click", function (e) {
          e.preventDefault();
          api.logout();
        });
      }
    });

    var user = session.user();
    if (user) {
      var slots = document.querySelectorAll("[data-user-name]");
      Array.prototype.forEach.call(slots, function (slot) {
        slot.textContent = user.name || user.email;
      });
    }
  }

  global.IE = {
    api: api,
    session: session,
    requireLogin: requireLogin,
    homeFor: homeFor,
    fmt: fmt,
    esc: esc,
    qs: qs,
    byId: byId,
    setText: setText,
    setHTML: setHTML,
    notify: notify,
    empty: empty,
    loading: loading,
    boot: boot
  };
})(window);
