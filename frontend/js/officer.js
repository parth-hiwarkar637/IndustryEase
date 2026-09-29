/*
 * officer.js
 * ----------
 * The government officer pages: dashboard, application review, raise query,
 * schedule inspection and record decision.
 *
 * This is the browser half of the hackathon backend's government.py, which
 * used to be a terminal menu that edited projects.json directly.
 */

(function () {
  "use strict";

  var IE = window.IE;
  var api = IE.api;
  var esc = IE.esc;
  var fmt = IE.fmt;
  var page = document.body.dataset.page;
  var officer = null;

  /* =============================================  OFFICER DASHBOARD  ===== */

  function initDashboard() {
    var list = IE.byId("officerApplications");
    IE.loading(list, "Loading the review queue…");

    return Promise.all([
      api.get("/officer/stats"),
      api.get("/officer/applications")
    ]).then(function (results) {
      var stats = results[0];
      var applications = results[1];

      IE.setText("officerTotal", fmt.pad(stats.total));
      IE.setText("officerPending", fmt.pad(stats.pending));
      IE.setText("officerApproved", fmt.pad(stats.approved));
      IE.setText("officerRejected", fmt.pad(stats.rejected));

      var welcome = document.querySelector(".welcome-card h1, .welcome-card h2");
      if (welcome && officer) {
        welcome.textContent = "Welcome, " + officer.name;
      }

      if (!applications.length) {
        IE.empty(list, "No applications have been submitted for review yet.");
        return;
      }

      list.innerHTML = applications.map(function (a) {
        return '<div class="application-row">' +
            '<div class="application-info">' +
              "<h3>" + esc(a.reference) + "</h3>" +
              "<p>" + esc(a.business_name) + "</p>" +
            "</div>" +
            '<div class="approval-name">' + esc(a.approval_name) + "</div>" +
            '<span class="status ' + fmt.statusClass(a.status) + '">' +
              esc(fmt.label(a.status)) + "</span>" +
            '<a href="application-review.html?application=' + encodeURIComponent(a.id) +
              '" class="review-btn">Review →</a>' +
          "</div>";
      }).join("");
    });
  }

  /* ==============================================  APPLICATION REVIEW  ===== */

  function initReview() {
    return resolveApplication().then(function (applicationId) {
      if (!applicationId) {
        IE.notify("No application selected.", "error");
        return;
      }

      return api.get("/officer/applications/" + encodeURIComponent(applicationId))
        .then(function (a) {
          var project = a.project || {};

          IE.setHTML("reviewApplicationInfo",
            cell("Applicant / Business", a.business_name) +
            cell("Approval", a.approval_name) +
            cell("Department", a.department) +
            cell("Submitted On", fmt.date(a.submitted_at)) +
            cell("Reference", a.reference) +
            cell("Current Status", fmt.label(a.status)));

          IE.setHTML("reviewProjectInfo",
            cell("Project Name", project.project_name) +
            cell("Industry Type", project.sector_label || fmt.label(project.sector)) +
            cell("Location", project.location) +
            cell("Investment", fmt.money(project.investment)) +
            cell("Employees", project.employees) +
            cell("Contact", a.applicant_phone || a.applicant_email));

          var description = document.querySelector(".description");
          if (description && project.description) {
            description.textContent = project.description;
          }

          IE.setText("reviewReference", a.reference);
          renderReviewDocuments(a.documents);
          renderStatusBadge(a.status);
          wireActionButtons(applicationId);
        });
    });
  }

  function renderReviewDocuments(documents) {
    var host = IE.byId("reviewDocuments");
    if (!host) return;

    if (!documents || !documents.length) {
      host.innerHTML = '<div class="ie-empty"><p>No documents uploaded.</p></div>';
      return;
    }

    host.innerHTML = documents.map(function (d) {
      return '<div class="document-item">' +
          "<div><h3>" + esc(fmt.label(d.doc_type)) + "</h3>" +
          "<p>" + esc(d.filename) + "</p></div>" +
          '<span class="document-status">' + esc(fmt.label(d.status)) + "</span>" +
        "</div>";
    }).join("");
  }

  function renderStatusBadge(status) {
    var badge = document.querySelector(".page-header .status");
    if (!badge) return;
    badge.textContent = fmt.label(status);
    badge.className = "status " + fmt.statusClass(status);
  }

  function wireActionButtons(applicationId) {
    var suffix = "?application=" + encodeURIComponent(applicationId);
    var map = {
      actionQuery: "queries.html",
      actionInspection: "inspections.html",
      actionDecision: "decision.html"
    };
    Object.keys(map).forEach(function (id) {
      var link = IE.byId(id);
      if (link) link.setAttribute("href", map[id] + suffix);
    });
  }

  /* ========================================================  QUERIES  ===== */

  function initQueries() {
    return resolveApplication().then(function (applicationId) {
      if (!applicationId) {
        IE.notify("Open an application from the dashboard first.", "error");
        return;
      }

      return api.get("/officer/applications/" + encodeURIComponent(applicationId))
        .then(function (a) {
          IE.setText("queryApprovalName", a.approval_name);
          IE.setText("queryReference", a.reference + " · " + a.business_name);
          setBadge("queryStatus", a.status);

          renderPreviousQueries(a.queries);
          wireQueryForm(applicationId);
        });
    });
  }

  function renderPreviousQueries(queries) {
    var host = IE.byId("previousQueries");
    if (!host) return;

    if (!queries || !queries.length) {
      host.innerHTML = '<div class="empty-query">No queries have been raised yet.</div>';
      return;
    }

    host.innerHTML = queries.map(function (q) {
      return '<div class="ie-query-item">' +
          "<h4>" + esc(fmt.label(q.query_type)) + " · " +
            esc(fmt.shortDate(q.created_at)) + "</h4>" +
          "<p>" + esc(q.message) + "</p>" +
          (q.respond_by ? '<p class="ie-meta">Response requested by ' +
            fmt.date(q.respond_by) + "</p>" : "") +
          (q.response
            ? '<div class="ie-answer"><strong>Applicant replied:</strong><br>' +
              esc(q.response) + "</div>"
            : '<p class="ie-meta">Awaiting a response.</p>') +
        "</div>";
    }).join("");
  }

  function wireQueryForm(applicationId) {
    var form = IE.byId("queryForm");
    if (!form) return;

    var button = form.querySelector("button[type=submit]");

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var payload = {
        query_type: value("queryType"),
        message: value("queryMessage"),
        respond_by: value("responseDate")
      };

      if (!payload.query_type) {
        IE.notify("Please choose a query type.", "error");
        return;
      }
      if (!payload.message) {
        IE.notify("Please write the query message.", "error");
        return;
      }

      button.disabled = true;
      button.textContent = "Sending…";

      api.post("/officer/applications/" + encodeURIComponent(applicationId) + "/query", payload)
        .then(function () {
          IE.notify("Query sent to the applicant.", "success");
          form.reset();
          button.disabled = false;
          button.textContent = "Send Query";
          return initQueries();
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Send Query";
        });
    });
  }

  /* ====================================================  INSPECTIONS  ===== */

  function initInspections() {
    return resolveApplication().then(function (applicationId) {
      if (!applicationId) {
        IE.notify("Open an application from the dashboard first.", "error");
        return;
      }

      return api.get("/officer/applications/" + encodeURIComponent(applicationId))
        .then(function (a) {
          IE.setText("inspectionApprovalName", a.approval_name);
          IE.setText("inspectionReference", a.reference + " · " + a.business_name);
          setBadge("inspectionAppStatus", a.status);

          // Pre-fill the obvious fields so the officer types less.
          var project = a.project || {};
          if (!value("inspectionLocation")) {
            setValue("inspectionLocation", project.location || "");
          }
          if (!value("officerName")) {
            setValue("officerName", officer.name || "");
          }

          renderScheduledInspections(a.inspections);
          wireInspectionForm(applicationId);
        });
    });
  }

  function renderScheduledInspections(inspections) {
    var host = IE.byId("scheduledInspections");
    if (!host) return;

    if (!inspections || !inspections.length) {
      host.innerHTML = '<div class="ie-empty"><p>No inspection scheduled yet.</p></div>';
      return;
    }

    host.innerHTML = inspections.map(function (i) {
      return '<div class="ie-inspection-item">' +
          "<h4>" + esc(i.purpose) + "</h4>" +
          "<p>" + fmt.date(i.inspection_date) + " at " + esc(i.inspection_time) + "</p>" +
          "<p>" + esc(i.location) + "</p>" +
          '<p class="ie-meta">Officer: ' + esc(i.officer_name) +
            " · " + esc(fmt.label(i.status)) + "</p>" +
          (i.notes ? "<p>" + esc(i.notes) + "</p>" : "") +
        "</div>";
    }).join("");
  }

  function wireInspectionForm(applicationId) {
    var form = IE.byId("inspectionForm");
    if (!form) return;

    var button = form.querySelector("button[type=submit]");

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var payload = {
        inspection_date: value("inspectionDate"),
        inspection_time: value("inspectionTime"),
        location: value("inspectionLocation"),
        purpose: value("inspectionPurpose"),
        officer_name: value("officerName"),
        notes: value("inspectionNotes")
      };

      button.disabled = true;
      button.textContent = "Scheduling…";

      api.post("/officer/applications/" + encodeURIComponent(applicationId) + "/inspection",
               payload)
        .then(function () {
          IE.notify("Inspection scheduled and the applicant has been notified.", "success");
          form.reset();
          button.disabled = false;
          button.textContent = "Schedule Inspection";
          return initInspections();
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Schedule Inspection";
        });
    });
  }

  /* =======================================================  DECISION  ===== */

  function initDecision() {
    return resolveApplication().then(function (applicationId) {
      if (!applicationId) {
        IE.notify("Open an application from the dashboard first.", "error");
        return;
      }

      return api.get("/officer/applications/" + encodeURIComponent(applicationId))
        .then(function (a) {
          var project = a.project || {};

          IE.setText("decisionApprovalName", a.approval_name);
          IE.setText("decisionReference", a.reference + " · " + a.business_name);
          setBadge("decisionStatus", a.status);

          IE.setHTML("decisionSummary",
            reviewItem("Project", project.project_name) +
            reviewItem("Business", a.business_name) +
            reviewItem("Approval", a.approval_name) +
            reviewItem("Department", a.department) +
            reviewItem("Investment", fmt.money(project.investment)) +
            reviewItem("Employees", project.employees) +
            reviewItem("Documents", (a.documents || []).length + " uploaded") +
            reviewItem("Inspections", (a.inspections || []).length + " scheduled"));

          // Default the date field to today.
          var dateField = IE.byId("decisionDate");
          if (dateField && !dateField.value) {
            dateField.value = new Date().toISOString().slice(0, 10);
          }

          if (a.status === "approved" || a.status === "rejected") {
            showResult(a.status, a.remarks);
            disableForm();
            return;
          }

          wireDecisionForm(applicationId);
        });
    });
  }

  function wireDecisionForm(applicationId) {
    var form = IE.byId("decisionForm");
    if (!form) return;

    var button = form.querySelector("button[type=submit]");

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var payload = {
        decision: value("decision"),
        remarks: value("remarks"),
        decision_date: value("decisionDate")
      };

      if (!payload.decision) {
        IE.notify("Please select a decision.", "error");
        return;
      }
      if (!payload.remarks) {
        IE.notify("Please enter remarks explaining the decision.", "error");
        return;
      }

      button.disabled = true;
      button.textContent = "Recording…";

      api.post("/officer/applications/" + encodeURIComponent(applicationId) + "/decision",
               payload)
        .then(function () {
          showResult(payload.decision, payload.remarks);
          disableForm();
          IE.notify("Decision recorded.", "success");
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Submit Decision";
        });
    });
  }

  function showResult(decision, remarks) {
    var card = IE.byId("resultCard");
    var message = IE.byId("resultMessage");

    if (card) card.style.display = "block";
    if (!message) return;

    if (decision === "approved") {
      message.textContent =
        "Application approved. Compliance tasks and the licence renewal " +
        "schedule have been created for the applicant.";
    } else if (decision === "rejected") {
      message.textContent = "Application rejected. " + remarks;
    } else {
      message.textContent =
        "More information has been requested. The applicant has been sent a query.";
    }
  }

  function disableForm() {
    var form = IE.byId("decisionForm");
    if (!form) return;
    Array.prototype.forEach.call(form.elements, function (el) {
      el.disabled = true;
    });
    var button = form.querySelector("button[type=submit]");
    if (button) button.textContent = "Decision Recorded";
  }

  /* ========================================================  HELPERS  ===== */

  function cell(label, value) {
    return "<div><span>" + esc(label) + "</span><strong>" +
           esc(value === 0 ? "0" : (value || "—")) + "</strong></div>";
  }

  function reviewItem(label, value) {
    return '<div class="review-item"><span>' + esc(label) + "</span><strong>" +
           esc(value === 0 ? "0" : (value || "—")) + "</strong></div>";
  }

  function setBadge(id, status) {
    var el = IE.byId(id);
    if (!el) return;
    el.textContent = fmt.label(status);
    el.className = "status " + fmt.statusClass(status);
  }

  function value(id) {
    var el = IE.byId(id);
    return el ? String(el.value).trim() : "";
  }

  function setValue(id, val) {
    var el = IE.byId(id);
    if (el && val !== null && val !== undefined) el.value = val;
  }

  /**
   * Officer pages are always about one application. Use ?application= when it
   * is there, otherwise fall back to the oldest one still awaiting review so
   * the page is never empty.
   */
  function resolveApplication() {
    var fromUrl = IE.qs("application");
    if (fromUrl) return Promise.resolve(fromUrl);

    return api.get("/officer/applications").then(function (applications) {
      if (!applications.length) return null;
      var pending = applications.filter(function (a) {
        return a.status !== "approved" && a.status !== "rejected";
      });
      var chosen = pending.length ? pending[pending.length - 1] : applications[0];
      return chosen.id;
    });
  }

  /* ==========================================================  ROUTES  ===== */

  var routes = {
    "officer-dashboard": initDashboard,
    "application-review": initReview,
    "queries": initQueries,
    "inspections": initInspections,
    "decision": initDecision
  };

  IE.boot(function () {
    officer = IE.requireLogin("officer");
    if (!officer) return;

    var init = routes[page];
    if (init) return init();
  });
})();
