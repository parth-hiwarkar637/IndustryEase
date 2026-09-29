/*
 * auth.js
 * -------
 * The public pages: landing, login and register.
 *
 * The old login.html compared the email and password against two hardcoded
 * strings in the browser. It now posts to /api/auth/login and stores the
 * returned token. The same demo credentials still work, because seed.py
 * creates real accounts for them.
 */

(function () {
  "use strict";

  var IE = window.IE;
  var page = document.body.dataset.page;

  /* ------------------------------------------------------------- landing */

  function initIndex() {
    var user = IE.session.user();
    if (!user) return;

    // Already signed in: swap Login/Register in the navbar for a way back in.
    var nav = document.querySelector(".nav-links");
    if (!nav) return;

    var login = nav.querySelector('a[href="login.html"]');
    var register = nav.querySelector('a[href="register.html"]');
    if (login) {
      login.textContent = "Dashboard";
      login.setAttribute("href", IE.homeFor(user));
    }
    if (register) {
      register.textContent = "Logout";
      register.setAttribute("href", "#");
      register.addEventListener("click", function (e) {
        e.preventDefault();
        IE.api.logout();
      });
    }

    var cta = document.querySelector(".hero-buttons .primary-btn");
    if (cta) {
      cta.textContent = "Go to Dashboard";
      cta.setAttribute("href", IE.homeFor(user));
    }
  }

  /* --------------------------------------------------------------- login */

  function initLogin() {
    if (IE.qs("expired")) {
      IE.notify("Your session expired. Please log in again.", "error");
    }

    // Already signed in? Skip straight through.
    var existing = IE.session.user();
    if (existing) {
      location.href = IE.homeFor(existing);
      return;
    }

    var form = IE.byId("loginForm");
    if (!form) return;

    var emailField = IE.byId("email");
    var roleInputs = form.querySelectorAll('input[name="role"]');
    var button = form.querySelector("button[type=submit]");

    // Keep the placeholder honest as the role toggle changes.
    function syncPlaceholder() {
      var role = form.querySelector('input[name="role"]:checked').value;
      emailField.placeholder = role === "officer"
        ? "Enter your officer ID (e.g. OFF-1001)"
        : "Enter your email address";
    }

    Array.prototype.forEach.call(roleInputs, function (input) {
      input.addEventListener("change", syncPlaceholder);
    });
    syncPlaceholder();

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var role = form.querySelector('input[name="role"]:checked').value;
      var identifier = emailField.value.trim();
      var password = IE.byId("password").value;

      if (!identifier || !password) {
        IE.notify("Please enter both your login ID and password.", "error");
        return;
      }

      button.disabled = true;
      button.textContent = "Signing in…";

      IE.api.login(identifier, password, role)
        .then(function (data) {
          location.href = IE.homeFor(data.user);
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Login";
        });
    });
  }

  /* ------------------------------------------------------------ register */

  function initRegister() {
    var form = IE.byId("registerForm");
    if (!form) return;

    var button = form.querySelector("button[type=submit]");

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var name = IE.byId("name").value.trim();
      var email = IE.byId("email").value.trim();
      var phone = IE.byId("phone").value.trim();
      var password = IE.byId("password").value;
      var confirm = IE.byId("confirm-password").value;

      if (password !== confirm) {
        IE.notify("The two passwords do not match.", "error");
        return;
      }
      if (password.length < 6) {
        IE.notify("Please choose a password of at least 6 characters.", "error");
        return;
      }

      button.disabled = true;
      button.textContent = "Creating account…";

      IE.api.register({
        name: name,
        email: email,
        phone: phone,
        password: password,
        role: "entrepreneur"
      })
        .then(function () {
          // New accounts have no project yet, so start them at the form
          // that unlocks everything else.
          location.href = "project.html";
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Create Account";
        });
    });
  }

  var routes = {
    "index": initIndex,
    "login": initLogin,
    "register": initRegister
  };

  IE.boot(function () {
    var init = routes[page];
    if (init) init();
  });
})();
