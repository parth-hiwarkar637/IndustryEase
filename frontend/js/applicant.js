/*
 * applicant.js
 * ------------
 * Every entrepreneur-facing page: dashboard, business profile, project,
 * approvals, approval details, documents, tracking, compliance, renewals,
 * schemes and scheme details.
 *
 * All of these used to render hardcoded demo content. They now read from the
 * API and render whatever the signed-in user actually has.
 */

(function () {
  "use strict";

  var IE = window.IE;
  var api = IE.api;
  var esc = IE.esc;
  var fmt = IE.fmt;
  var page = document.body.dataset.page;
  var user = null;

  /* =====================================================  DASHBOARD  ===== */

  function initDashboard() {
    return api.get("/dashboard").then(function (data) {
      IE.setText("statApprovals", fmt.pad(data.approvals));
      IE.setText("statApplications", fmt.pad(data.applications_in_progress));
      IE.setText("statCompliance", fmt.pad(data.compliance_pending));
      IE.setText("statRenewals", fmt.pad(data.renewals_due));

      var subtitle = IE.byId("dashboardSubtitle");
      if (!subtitle) return;

      if (data.project) {
        subtitle.textContent =
          data.project.project_name + " · " + data.project.location +
          " · " + fmt.money(data.project.investment);
      } else {
        subtitle.textContent =
          "Add your project details to see the approvals that apply to you.";
        IE.notify(
          "You have not added a project yet. Start with Project Details.",
          "info"
        );
      }

      if (data.open_queries > 0) {
        IE.notify(
          data.open_queries + " query/queries need your response. " +
          "Open Application Tracking to reply.",
          "info"
        );
      }
    });
  }

  /* ==============================================  BUSINESS PROFILE  ===== */

  function initProfile() {
    var form = IE.byId("profileForm");
    if (!form) return;

    var button = form.querySelector("button[type=submit]");

    return api.get("/profile").then(function (profile) {
      if (profile && profile.business_name) {
        setValue("business-name", profile.business_name);
        setValue("business-type", profile.business_type);
        setValue("industry", profile.industry);
        setValue("state", profile.state);
        setValue("employees", profile.employees);
      }

      form.addEventListener("submit", function (event) {
        event.preventDefault();
        button.disabled = true;

        api.put("/profile", {
          business_name: value("business-name"),
          business_type: value("business-type"),
          industry: value("industry"),
          state: value("state"),
          employees: Number(value("employees") || 0)
        })
          .then(function () {
            return api.get("/auth/me");
          })
          .then(function (me) {
            IE.session.update(me);
            IE.notify("Business profile saved.", "success");
            button.disabled = false;
          })
          .catch(function (err) {
            IE.notify(err.message, "error");
            button.disabled = false;
          });
      });
    });
  }

  /* ================================================  PROJECT DETAILS  ===== */

  function initProject() {
    var form = IE.byId("projectForm");
    if (!form) return;

    var button = form.querySelector("button[type=submit]");
    var existingId = null;

    return api.get("/projects/current").then(function (project) {
      if (project && project.id) {
        existingId = project.id;
        setValue("projectName", project.project_name);
        setValue("businessName", project.business_name);
        setValue("industryType", denormalise(project.sector));
        setValue("location", project.location);
        setValue("investment", project.investment);
        setValue("employees", project.employees);
        setValue("description", project.description);
        button.textContent = "Update & Continue →";
      }

      form.addEventListener("submit", function (event) {
        event.preventDefault();

        var payload = {
          project_name: value("projectName"),
          business_name: value("businessName"),
          sector: value("industryType"),
          location: value("location"),
          investment: Number(value("investment") || 0),
          employees: Number(value("employees") || 0),
          description: value("description"),
          sector_label: selectedLabel("industryType")
        };

        if (!payload.sector) {
          IE.notify("Please select an industry type.", "error");
          return;
        }

        button.disabled = true;
        button.textContent = "Saving…";

        var request = existingId
          ? api.put("/projects/" + existingId, payload)
          : api.post("/projects", payload);

        request
          .then(function (project) {
            location.href = "approvals.html?project=" + encodeURIComponent(project.id);
          })
          .catch(function (err) {
            IE.notify(err.message, "error");
            button.disabled = false;
            button.textContent = "Save & Continue →";
          });
      });
    });
  }

  /** "food_processing" -> "food-processing" to match the <select> values. */
  function denormalise(sector) {
    return String(sector || "").replace(/_/g, "-");
  }

  /* =====================================================  APPROVALS  ===== */

  function initApprovals() {
    var container = IE.byId("approvalContainer");
    var summary = IE.byId("projectSummary");
    var projectId = IE.qs("project") || "";

    IE.loading(container, "Working out which approvals apply…");

    return api.get("/approvals" + (projectId ? "?project_id=" + encodeURIComponent(projectId) : ""))
      .then(function (data) {
        renderProjectSummary(summary, data.project);
        renderApprovalCards(container, data.project, data.approvals);
        wireApprovalSearch();
      })
      .catch(function (err) {
        IE.empty(container, err.message, "project.html", "Add project details");
        if (summary) summary.innerHTML = "";
      });
  }

  function renderProjectSummary(host, project) {
    if (!host || !project) return;
    host.innerHTML =
      '<div class="summary-header">' +
        "<div>" +
          '<p class="summary-label">YOUR PROJECT</p>' +
          "<h2>" + esc(project.project_name) + "</h2>" +
        "</div>" +
        '<a href="project.html" class="edit-project">Edit Project</a>' +
      "</div>" +
      '<div class="summary-details">' +
        infoCell("Industry Type", project.sector_label || fmt.label(project.sector)) +
        infoCell("Location", project.location) +
        infoCell("Investment", fmt.money(project.investment)) +
        infoCell("Employees", project.employees) +
      "</div>";
  }

  function infoCell(label, value) {
    return "<div><span>" + esc(label) + "</span><strong>" +
           esc(value === 0 ? "0" : (value || "—")) + "</strong></div>";
  }

  function renderApprovalCards(container, project, approvals) {
    if (!container) return;

    if (!approvals.length) {
      IE.empty(container,
        "No approvals matched this project. Check the industry type and employee count.",
        "project.html", "Edit project");
      return;
    }

    container.innerHTML = approvals.map(function (a) {
      var statusText, statusClass;

      if (a.application_status) {
        statusText = fmt.label(a.application_status);
        statusClass = fmt.statusClass(a.application_status);
      } else if (a.mandatory) {
        statusText = "Required";
        statusClass = "required";
      } else {
        statusText = "Check Eligibility";
        statusClass = "pending";
      }

      var action = a.application_id
        ? '<a href="' + (a.application_status === "draft"
            ? "documents.html?application=" + encodeURIComponent(a.application_id)
            : "tracking.html?application=" + encodeURIComponent(a.application_id)) + '">' +
          (a.application_status === "draft" ? "Continue Application →" : "Track Application →") +
          "</a>"
        : '<button type="button" class="ie-inline-btn" data-apply="' + esc(a.slug) + '">Start Application</button>';

      return '<div class="approval-card">' +
          '<div class="approval-top">' +
            "<h3>" + esc(a.name) + "</h3>" +
            '<span class="status ' + statusClass + '">' + esc(statusText) + "</span>" +
          "</div>" +
          "<p>" + esc(a.description) + "</p>" +
          '<p class="ie-meta">' + esc(a.department) +
            ' · <span class="ie-priority ie-priority-' + esc(String(a.priority).toLowerCase()) +
            '">' + esc(a.priority) + " PRIORITY</span>" +
            (a.inspection_required ? " · Inspection required" : "") +
          "</p>" +
          '<a href="approval-details.html?type=' + encodeURIComponent(a.slug) + '">View Details →</a>' +
          '<div style="margin-top:12px">' + action + "</div>" +
        "</div>";
    }).join("");

    container.addEventListener("click", function (event) {
      var button = event.target.closest("[data-apply]");
      if (!button) return;

      button.disabled = true;
      button.textContent = "Starting…";

      api.post("/applications", {
        project_id: project.id,
        approval_slug: button.dataset.apply
      })
        .then(function (application) {
          location.href = "documents.html?application=" + encodeURIComponent(application.id);
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Start Application";
        });
    });
  }

  function wireApprovalSearch() {
    var input = IE.byId("approvalSearch");
    var button = IE.byId("approvalSearchBtn");
    if (!input) return;

    function run() {
      var term = input.value.toLowerCase();
      var cards = document.querySelectorAll(".approval-card");
      Array.prototype.forEach.call(cards, function (card) {
        var title = card.querySelector("h3").textContent.toLowerCase();
        var body = card.textContent.toLowerCase();
        card.style.display = (title.includes(term) || body.includes(term)) ? "block" : "none";
      });
    }

    input.addEventListener("input", run);
    if (button) button.addEventListener("click", run);
  }

  /* ===============================================  APPROVAL DETAILS  ===== */

  function initApprovalDetails() {
    var slug = IE.qs("type") || "business";

    return api.get("/approvals/catalog/" + encodeURIComponent(slug))
      .then(function (approval) {
        IE.setText("approval-title", approval.name);
        IE.setText("approval-description", approval.description);
        IE.setText("approval-type", approval.name);
        IE.setText("department", approval.department);
        IE.setText("fee", approval.fee);
        IE.setText("processing", approval.processing_time);
        IE.setText("eligibility", approval.eligibility);

        IE.setHTML("documents", approval.documents.map(function (d) {
          return "<li><strong>" + esc(d.name) + "</strong>" +
                 (d.hint ? "<br><span>" + esc(d.hint) + "</span>" : "") + "</li>";
        }).join(""));

        return wireApplyButton(slug);
      })
      .catch(function (err) {
        IE.notify(err.message, "error");
      });
  }

  function wireApplyButton(slug) {
    var button = IE.byId("applyButton");
    if (!button) return;

    return api.get("/projects/current").then(function (project) {
      if (!project || !project.id) {
        button.textContent = "Add Project Details First";
        button.setAttribute("href", "project.html");
        return;
      }

      button.setAttribute("href", "#");
      button.addEventListener("click", function (event) {
        event.preventDefault();
        button.textContent = "Starting…";

        api.post("/applications", { project_id: project.id, approval_slug: slug })
          .then(function (application) {
            location.href = "documents.html?application=" + encodeURIComponent(application.id);
          })
          .catch(function (err) {
            IE.notify(err.message, "error");
            button.textContent = "Apply for this Approval";
          });
      });
    });
  }

  /* =====================================================  DOCUMENTS  ===== */

  function initDocuments() {
    var list = IE.byId("documentList");
    IE.loading(list, "Loading your document checklist…");

    return resolveApplication("draft").then(function (applicationId) {
      if (!applicationId) {
        IE.empty(list, "You have not started an application yet.",
                 "approvals.html", "Browse approvals");
        return;
      }
      return loadDocuments(applicationId);
    });
  }

  function loadDocuments(applicationId) {
    return api.get("/applications/" + encodeURIComponent(applicationId) + "/documents")
      .then(function (data) {
        var application = data.application;

        IE.setText("documentsApprovalName", application.approval_name);
        IE.setText("documentsProjectName",
                   application.reference + " · " + application.department);

        renderDocumentRows(data, applicationId);
        updateSubmitState(data, application, applicationId);
      });
  }

  function renderDocumentRows(data, applicationId) {
    var list = IE.byId("documentList");
    if (!list) return;

    list.innerHTML = data.documents.map(function (doc, index) {
      var status = doc.uploaded
        ? '<span class="upload-status uploaded">✓ ' + esc(doc.filename) + "</span>"
        : '<span class="upload-status">Not Uploaded</span>';

      return '<div class="document-row">' +
          '<div class="document-info">' +
            '<div class="document-number">' + fmt.pad(index + 1) + "</div>" +
            "<div>" +
              "<h3>" + esc(doc.name) + "</h3>" +
              "<p>" + esc(doc.hint) + "</p>" +
              status +
            "</div>" +
          "</div>" +
          '<label class="upload-btn">' +
            (doc.uploaded ? "Replace File" : "Choose File") +
            '<input type="file" class="document-input" data-key="' + esc(doc.key) + '"' +
            ' accept=".pdf,.jpg,.jpeg,.png,.docx">' +
          "</label>" +
        "</div>";
    }).join("");

    list.addEventListener("change", function (event) {
      var input = event.target;
      if (!input.classList.contains("document-input")) return;
      if (!input.files.length) return;

      var label = input.closest(".upload-btn");
      var original = label.firstChild.nodeValue;
      label.firstChild.nodeValue = "Uploading… ";

      var form = new FormData();
      form.append("application_id", applicationId);
      form.append("doc_type", input.dataset.key);
      form.append("file", input.files[0]);

      api.upload("/documents/upload", form)
        .then(function () {
          return loadDocuments(applicationId);
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          label.firstChild.nodeValue = original;
          input.value = "";
        });
    });
  }

  function updateSubmitState(data, application, applicationId) {
    var button = IE.byId("submitButton");
    var message = IE.byId("submitMessage");
    var status = IE.byId("applicationStatus");

    var uploaded = data.documents.filter(function (d) { return d.uploaded; }).length;
    var total = data.documents.length;
    var alreadySubmitted = application.status !== "draft";

    if (status) {
      status.textContent = alreadySubmitted
        ? fmt.label(application.status)
        : (data.complete ? "Ready to Submit" : "Documents Pending");
      status.className = "status " +
        (alreadySubmitted ? fmt.statusClass(application.status)
                          : (data.complete ? "ready" : "pending"));
    }

    if (message) {
      message.textContent = alreadySubmitted
        ? "This application has already been submitted."
        : (data.complete
            ? "All required documents are ready for submission."
            : uploaded + " of " + total + " documents uploaded.");
    }

    if (!button) return;

    if (alreadySubmitted) {
      button.disabled = true;
      button.textContent = "Already Submitted";
      return;
    }

    button.disabled = !data.complete;
    button.onclick = function () {
      if (!confirm("Are you sure you want to submit this application?")) return;

      button.disabled = true;
      button.textContent = "Submitting…";

      api.post("/applications/" + encodeURIComponent(applicationId) + "/submit")
        .then(function () {
          location.href = "tracking.html?application=" + encodeURIComponent(applicationId);
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
          button.textContent = "Submit Application";
        });
    };
  }

  /* ======================================================  TRACKING  ===== */

  function initTracking() {
    return resolveApplication("submitted").then(function (applicationId) {
      if (!applicationId) {
        IE.notify("You have not submitted an application yet.", "info");
        var timeline = document.querySelector(".timeline");
        IE.empty(timeline, "Nothing to track yet.", "approvals.html", "Browse approvals");
        return;
      }
      return loadTracking(applicationId);
    });
  }

  function loadTracking(applicationId) {
    return Promise.all([
      api.get("/applications/" + encodeURIComponent(applicationId) + "/tracking"),
      api.get("/applications")
    ]).then(function (results) {
      var data = results[0];
      var all = results[1].filter(function (a) { return a.status !== "draft"; });
      var application = data.application;

      IE.setText("trackingApprovalName", application.approval_name);
      IE.setText("trackingReference",
                 application.reference + " · " + application.department);

      var status = IE.byId("currentStatus");
      if (status) {
        status.textContent = fmt.label(application.status);
        status.className = "status " + fmt.statusClass(application.status);
      }

      renderSwitcher(all, applicationId);
      renderTimeline(data);
      renderTrackingDetails(data);
    });
  }

  function renderSwitcher(applications, currentId) {
    var host = IE.byId("trackingSwitcher");
    if (!host || applications.length < 2) return;

    host.innerHTML = '<div class="ie-switcher">' + applications.map(function (a) {
      return '<button type="button" data-app="' + esc(a.id) + '"' +
             (a.id === currentId ? ' class="is-active"' : "") + ">" +
             esc(a.approval_name) + "</button>";
    }).join("") + "</div>";

    host.addEventListener("click", function (event) {
      var button = event.target.closest("[data-app]");
      if (!button) return;
      location.href = "tracking.html?application=" + encodeURIComponent(button.dataset.app);
    });
  }

  function renderTimeline(data) {
    var timeline = document.querySelector(".timeline");
    if (!timeline) return;

    var icons = { completed: "✓", pending: "●", rejected: "✕", cancelled: "—", locked: "○" };

    timeline.innerHTML = data.steps.map(function (step) {
      var state = step.status === "completed" ? "completed"
                : step.status === "pending" ? "active" : "";

      var extra = "";
      if (step.stage === "inspection" && data.inspections.length) {
        var i = data.inspections[0];
        extra = "<br><span>Scheduled for " + fmt.date(i.inspection_date) +
                " at " + esc(i.inspection_time) + " · " + esc(i.location) + "</span>";
      }

      return '<div class="timeline-item ' + state + '">' +
          '<div class="timeline-icon">' + (icons[step.status] || "○") + "</div>" +
          '<div class="timeline-content">' +
            "<h3>" + esc(step.label) + "</h3>" +
            "<p>" + esc(step.remarks || step.description) + extra + "</p>" +
            "<span>" + (step.decided_at ? fmt.date(step.decided_at) : fmt.label(step.status)) +
            "</span>" +
          "</div>" +
        "</div>";
    }).join("");
  }

  function renderTrackingDetails(data) {
    var grid = document.querySelector(".details-grid");
    var application = data.application;
    var project = data.project || {};

    if (grid) {
      grid.innerHTML =
        detailCell("Application Number", application.reference) +
        detailCell("Approval", application.approval_name) +
        detailCell("Department", application.department) +
        detailCell("Project", project.project_name) +
        detailCell("Submitted On", fmt.date(application.submitted_at)) +
        detailCell("Current Status", fmt.label(application.status)) +
        detailCell("Documents Uploaded", data.documents.length) +
        detailCell("Last Updated", fmt.date(application.updated_at || application.created_at));
    }

    // Officer remarks and decision date, if a decision has been recorded.
    var remarksBox = IE.byId("remarksBox");
    if (remarksBox && application.remarks) {
      remarksBox.style.display = "block";
      IE.setText("officerRemarks", application.remarks);
    }

    var dateBox = IE.byId("decisionDateBox");
    if (dateBox && application.decided_at) {
      dateBox.style.display = "block";
      IE.setText("decisionDate", fmt.date(application.decided_at));
    }

    var complianceButton = IE.byId("complianceButton");
    if (complianceButton) {
      complianceButton.style.display =
        application.status === "approved" ? "inline-block" : "none";
    }

    renderOpenQueries(data.queries);
  }

  function detailCell(label, value) {
    return "<div><span>" + esc(label) + "</span><strong>" +
           esc(value === 0 ? "0" : (value || "—")) + "</strong></div>";
  }

  function renderOpenQueries(queries) {
    var open = (queries || []).filter(function (q) { return q.status === "open"; });
    if (!open.length) return;

    var host = document.querySelector(".tracking-card") || document.querySelector("main");
    var box = document.createElement("div");
    box.className = "details-card";
    box.innerHTML = "<h2>Queries from the Department</h2>" +
      open.map(function (q) {
        return '<div class="ie-query-item">' +
            "<h4>" + esc(fmt.label(q.query_type)) + " · " + esc(q.officer_name) + "</h4>" +
            "<p>" + esc(q.message) + "</p>" +
            (q.respond_by ? '<p class="ie-meta">Respond by ' + fmt.date(q.respond_by) + "</p>" : "") +
            '<textarea rows="3" data-query-response="' + esc(q.id) +
              '" placeholder="Type your response…" style="width:100%;margin-top:8px"></textarea>' +
            '<button type="button" class="ie-inline-btn" data-query-submit="' + esc(q.id) +
              '" style="margin-top:8px">Send Response</button>' +
          "</div>";
      }).join("");

    host.appendChild(box);

    box.addEventListener("click", function (event) {
      var button = event.target.closest("[data-query-submit]");
      if (!button) return;

      var id = button.dataset.querySubmit;
      var textarea = box.querySelector('[data-query-response="' + id + '"]');
      var text = textarea.value.trim();

      if (!text) {
        IE.notify("Please type a response before sending.", "error");
        return;
      }

      button.disabled = true;
      api.post("/queries/" + encodeURIComponent(id) + "/respond", { response: text })
        .then(function () {
          IE.notify("Your response has been sent.", "success");
          setTimeout(function () { location.reload(); }, 900);
        })
        .catch(function (err) {
          IE.notify(err.message, "error");
          button.disabled = false;
        });
    });
  }

  /* ====================================================  COMPLIANCE  ===== */

  function initCompliance() {
    var list = IE.byId("complianceList");
    IE.loading(list, "Loading your compliance tasks…");

    return api.get("/compliance").then(function (data) {
      IE.setText("complianceTotal", fmt.pad(data.total));
      IE.setText("complianceCompleted", fmt.pad(data.completed));
      IE.setText("compliancePending", fmt.pad(data.pending));
      IE.setText("complianceDueSoon", fmt.pad(data.due_soon));

      var badge = IE.byId("complianceBadge");
      if (badge) {
        badge.textContent = data.total
          ? "✓ " + data.completed + " of " + data.total + " complete"
          : "No obligations yet";
      }

      if (!data.items.length) {
        IE.empty(list,
          "Compliance tasks appear here once an application is approved.",
          "tracking.html", "Track applications");
        return;
      }

      list.innerHTML = data.items.map(function (item) {
        var cls = item.status === "completed" ? "completed"
                : item.status === "due_soon" ? "due-soon"
                : item.status === "overdue" ? "due-soon" : "pending";
        var icon = item.status === "completed" ? "✓" : "!";

        return '<div class="compliance-card">' +
            '<div class="compliance-info">' +
              '<div class="icon">' + esc(item.icon || "📄") + "</div>" +
              "<div>" +
                "<h3>" + esc(item.title) + "</h3>" +
                "<p>" + esc(item.description) + "</p>" +
                '<span class="due-date">Due: ' + fmt.date(item.due_date) +
                (item.days_remaining !== null && item.status !== "completed"
                  ? " · " + describeDays(item.days_remaining) : "") +
                "</span>" +
              "</div>" +
            "</div>" +
            '<div class="compliance-status ' + cls + '">' +
              "<span>" + icon + "</span>" + esc(fmt.label(item.status)) +
              (item.completed ? "" :
                '<button type="button" class="ie-inline-btn" data-complete="' +
                esc(item.id) + '" style="margin-left:10px">Mark Done</button>') +
            "</div>" +
          "</div>";
      }).join("");

      list.addEventListener("click", function (event) {
        var button = event.target.closest("[data-complete]");
        if (!button) return;

        button.disabled = true;
        api.post("/compliance/" + encodeURIComponent(button.dataset.complete) + "/complete")
          .then(function () {
            IE.notify("Marked as completed.", "success");
            return initCompliance();
          })
          .catch(function (err) {
            IE.notify(err.message, "error");
            button.disabled = false;
          });
      });
    });
  }

  function describeDays(days) {
    if (days === null || days === undefined) return "";
    if (days < 0) return Math.abs(days) + " days overdue";
    if (days === 0) return "due today";
    return days + " days remaining";
  }

  /* ======================================================  RENEWALS  ===== */

  function initRenewals() {
    var container = document.querySelector(".renewal-container");
    IE.loading(container, "Loading your licences…");

    return api.get("/renewals").then(function (data) {
      IE.setText("renewalTotal", fmt.pad(data.total));
      IE.setText("renewalActive", fmt.pad(data.active));
      IE.setText("renewalDueSoon", fmt.pad(data.due_soon));
      IE.setText("renewalExpired", fmt.pad(data.expired));

      if (!data.items.length) {
        IE.empty(container,
          "Licences appear here once an approval has been granted.",
          "tracking.html", "Track applications");
        return;
      }

      container.innerHTML = data.items.map(function (item) {
        var cls = item.status === "active" ? "active"
                : item.status === "due_soon" ? "due-soon" : "expired";

        return '<div class="renewal-card">' +
            '<div class="renewal-info">' +
              '<div class="renewal-icon">' + esc(item.icon || "📄") + "</div>" +
              "<div>" +
                "<h3>" + esc(item.title) + "</h3>" +
                "<p>Licence No: " + esc(item.licence_number) + "</p>" +
                "<span>Expiry Date: " + fmt.date(item.expiry_date) + "</span>" +
              "</div>" +
            "</div>" +
            '<div class="renewal-right">' +
              '<span class="status ' + cls + '">' + esc(fmt.label(item.status)) + "</span>" +
              '<p class="days">' + esc(describeDays(item.days_remaining)) + "</p>" +
              '<button type="button" class="ie-inline-btn" data-renew="' +
                esc(item.id) + '">Renew Now</button>' +
            "</div>" +
          "</div>";
      }).join("");

      container.addEventListener("click", function (event) {
        var button = event.target.closest("[data-renew]");
        if (!button) return;

        button.disabled = true;
        button.textContent = "Renewing…";

        api.post("/renewals/" + encodeURIComponent(button.dataset.renew) + "/renew")
          .then(function (row) {
            IE.notify("Renewed until " + fmt.date(row.expiry_date) + ".", "success");
            return initRenewals();
          })
          .catch(function (err) {
            IE.notify(err.message, "error");
            button.disabled = false;
            button.textContent = "Renew Now";
          });
      });
    });
  }

  /* =======================================================  SCHEMES  ===== */

  function initSchemes() {
    var grid = document.querySelector(".schemes-grid");
    IE.loading(grid, "Finding schemes for your business…");

    return api.get("/schemes").then(function (results) {
      if (!results.length) {
        IE.empty(grid, "No schemes are listed yet.");
        return;
      }

      grid.innerHTML = results.map(function (row) {
        var s = row.scheme;
        return '<div class="scheme-card" data-category="' + esc(s.category) + '">' +
            '<div class="scheme-top">' +
              '<div class="scheme-icon">' + esc(s.icon) + "</div>" +
              '<span class="scheme-status">' +
                (row.eligible ? "Relevant" : "Check eligibility") + "</span>" +
            "</div>" +
            "<h2>" + esc(s.name) + "</h2>" +
            '<p class="scheme-description">' + esc(s.description) + "</p>" +
            '<div class="scheme-details">' +
              infoCell("Category", s.category_label) +
              infoCell("Benefit", s.benefit) +
              infoCell("Department", s.department) +
            "</div>" +
            '<a href="scheme-details.html?scheme=' + encodeURIComponent(s.slug) +
              '" class="scheme-button">View Details →</a>' +
          "</div>";
      }).join("");

      wireSchemeFilter();
    });
  }

  function wireSchemeFilter() {
    var search = IE.byId("schemeSearch");
    var category = IE.byId("categoryFilter");
    if (!search || !category) return;

    function run() {
      var term = search.value.toLowerCase();
      var cat = category.value.toLowerCase();

      Array.prototype.forEach.call(
        document.querySelectorAll(".scheme-card"),
        function (card) {
          var text = card.innerText.toLowerCase();
          var cardCategory = card.getAttribute("data-category") || "";
          var matches = text.includes(term) &&
                        (cat === "all" || cardCategory.includes(cat));
          card.style.display = matches ? "block" : "none";
        }
      );
    }

    search.addEventListener("input", run);
    category.addEventListener("change", run);
  }

  /* ================================================  SCHEME DETAILS  ===== */

  function initSchemeDetails() {
    var slug = IE.qs("scheme") || "msme";

    return api.get("/schemes/" + encodeURIComponent(slug)).then(function (s) {
      IE.setText("schemeIcon", s.icon);
      IE.setText("schemeTitle", s.name);
      IE.setText("schemeDescription", s.description);
      IE.setText("schemeStatus", s.status);
      IE.setText("schemeOverview", s.overview);

      IE.setHTML("benefitsContainer", (s.benefits || []).map(function (b) {
        return '<div class="benefit-item">' +
            '<div class="benefit-icon">' + esc(b.icon) + "</div>" +
            "<div><h3>" + esc(b.title) + "</h3><p>" + esc(b.description) + "</p></div>" +
          "</div>";
      }).join(""));

      IE.setHTML("eligibilityList", (s.eligibility || []).map(function (item) {
        return "<li>" + esc(item) + "</li>";
      }).join(""));

      IE.setHTML("documentsContainer", (s.documents_required || []).map(function (d) {
        return '<div class="document-item">' + esc(d) + "</div>";
      }).join(""));

      IE.setHTML("processContainer", (s.process || []).map(function (step, i) {
        return '<div class="process-step">' +
            '<div class="step-number">' + (i + 1) + "</div>" +
            "<div><h3>" + esc(step) + "</h3></div>" +
          "</div>";
      }).join(""));

      IE.setText("actionTitle", "Interested in " + s.name + "?");
      IE.setText("actionDescription",
        "Check the eligibility conditions and required documents before applying " +
        "through the concerned department.");

      var apply = IE.byId("applyButton");
      if (apply) apply.setAttribute("href", "approvals.html");
    });
  }

  /* ========================================================  HELPERS  ===== */

  function value(id) {
    var el = IE.byId(id);
    return el ? String(el.value).trim() : "";
  }

  function setValue(id, val) {
    var el = IE.byId(id);
    if (el && val !== null && val !== undefined) el.value = val;
  }

  function selectedLabel(id) {
    var el = IE.byId(id);
    if (!el || !el.options) return "";
    var option = el.options[el.selectedIndex];
    return option ? option.text.trim() : "";
  }

  /**
   * Works out which application a page is about: the ?application= parameter
   * if present, otherwise the most sensible one the user has.
   */
  function resolveApplication(prefer) {
    var fromUrl = IE.qs("application");
    if (fromUrl) return Promise.resolve(fromUrl);

    return api.get("/applications").then(function (applications) {
      if (!applications.length) return null;

      var match;
      if (prefer === "draft") {
        match = applications.find(function (a) { return a.status === "draft"; });
      } else {
        match = applications.find(function (a) { return a.status !== "draft"; });
      }
      return (match || applications[0]).id;
    });
  }

  /* ==========================================================  ROUTES  ===== */

  var routes = {
    "dashboard": initDashboard,
    "business-profile": initProfile,
    "project": initProject,
    "approvals": initApprovals,
    "approval-details": initApprovalDetails,
    "documents": initDocuments,
    "tracking": initTracking,
    "compliance": initCompliance,
    "renewals": initRenewals,
    "schemes": initSchemes,
    "scheme-details": initSchemeDetails
  };

  IE.boot(function () {
    user = IE.requireLogin("entrepreneur");
    if (!user) return;

    var init = routes[page];
    if (init) return init();
  });
})();
