/* ============================================================
   HMT Watch Tracker - Shared frontend JavaScript
   ============================================================ */

"use strict";

/* ============================================================
   Tracker
   ============================================================ */

async function runTracker() {
    const button = document.getElementById("run-now-button");

    if (button) {
        button.disabled = true;
        button.textContent = "Running...";
    }

    showNotification("Tracker run started.", "success");

    try {
        const data = await apiPost("/api/run");
        const result = data.result || data.run || data;

        const newProducts = Number(result.new_products || 0);
        const alertsCreated = Number(result.alerts_created || 0);

        let message = "Tracker run completed.";

        if (newProducts > 0) {
            message += ` ${newProducts} new product${newProducts === 1 ? "" : "s"} found.`;
        }

        if (alertsCreated > 0) {
            message += ` ${alertsCreated} alert${alertsCreated === 1 ? "" : "s"} created.`;
        }

        showNotification(message, "success");

        window.setTimeout(() => {
            window.location.reload();
        }, 700);

        return data;

    } catch (error) {
        console.error("Tracker run failed:", error);

        const message = error.message || "Unable to run tracker.";

        if (
            message.toLowerCase().includes("already in progress") ||
            message.toLowerCase().includes("409")
        ) {
            showNotification(
                "A tracker run is already in progress. Please wait for it to finish.",
                "error"
            );
        } else {
            showNotification(message, "error");
        }

        return null;

    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = "Run Now";
        }
    }
}

/* ============================================================
   Notifications
   ============================================================ */

function showNotification(message, type = "success") {
    const area = document.getElementById("notification-area");

    if (!area) {
        return;
    }

    const notification = document.createElement("div");
    notification.className = `notification ${type}`;
    notification.textContent = message;

    area.appendChild(notification);

    window.setTimeout(() => {
        notification.remove();
    }, 4500);
}


/* ============================================================
   Shared API helpers
   ============================================================ */

async function readJsonResponse(response) {
    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        return await response.json();
    }

    const text = await response.text();

    return {
        detail: text || `Request failed: ${response.status}`
    };
}


async function apiGet(url) {
    const response = await fetch(url, {
        headers: {
            "Accept": "application/json"
        }
    });

    const data = await readJsonResponse(response);

    if (!response.ok) {
        throw new Error(
            data.detail ||
            data.error ||
            `Request failed: ${response.status}`
        );
    }

    return data;
}


async function apiPost(url, body = null) {
    const options = {
        method: "POST",
        headers: {
            "Accept": "application/json"
        }
    };

    if (body !== null) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);
    const data = await readJsonResponse(response);

    if (!response.ok) {
        throw new Error(
            data.detail ||
            data.error ||
            `Request failed: ${response.status}`
        );
    }

    return data;
}


/* ============================================================
   Shared formatting
   ============================================================ */

function formatDateTime(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return date.toLocaleString();
}


function formatCurrency(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (Number.isNaN(number)) {
        return String(value);
    }

    return "₹" + number.toLocaleString("en-IN", {
        maximumFractionDigits: 2
    });
}


function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* ============================================================
   Status helpers
   ============================================================ */

function getSchedulerStatus(data) {
    if (data && data.scheduler) {
        return data.scheduler;
    }

    return data || {};
}


function isTrackerRunning(data) {
    const scheduler = getSchedulerStatus(data);

    return (
        scheduler.running === true ||
        scheduler.status === "running" ||
        data?.running === true ||
        data?.status === "running"
    );
}


function isSchedulerRunning(data) {
    const scheduler = getSchedulerStatus(data);

    return scheduler.running === true;
}


function getLastRunAt(data) {
    const scheduler = getSchedulerStatus(data);

    return (
        scheduler.last_run_at ||
        scheduler.last_completed_run ||
        scheduler.last_run ||
        data?.last_run_at ||
        data?.last_completed_run ||
        data?.last_run ||
        null
    );
}


function getNextRunAt(data) {
    const scheduler = getSchedulerStatus(data);

    return (
        scheduler.next_run_at ||
        scheduler.next_run ||
        data?.next_run_at ||
        data?.next_run ||
        null
    );
}

/* ============================================================
   Periodic global status refresh
   ============================================================ */

async function refreshGlobalStatus() {
    try {
        const data = await apiGet("/api/status");

        const dot = document.getElementById("sidebar-status-dot");
        const text = document.getElementById("sidebar-status-text");

        if (!dot || !text) {
            return;
        }

        const trackerRunning = isTrackerRunning(data);
        const schedulerRunning = isSchedulerRunning(data);

        if (trackerRunning) {
            dot.className = "status-dot status-online";
            text.textContent = "Running";
            return;
        }

        if (schedulerRunning) {
            dot.className = "status-dot status-online";
            text.textContent = "Monitoring";
            return;
        }

        dot.className = "status-dot status-offline";
        text.textContent = "Scheduler stopped";
    } catch (error) {
        console.debug("Status refresh failed:", error);

        const dot = document.getElementById("sidebar-status-dot");
        const text = document.getElementById("sidebar-status-text");

        if (dot && text) {
            dot.className = "status-dot status-offline";
            text.textContent = "Unavailable";
        }
    }
}


/* ============================================================
   DOM startup
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
    refreshGlobalStatus();

    window.setInterval(refreshGlobalStatus, 30000);
});