"use strict";


/* ============================================================
   Tracker
   ============================================================ */

async function runTracker() {
    const button =
        document.getElementById("run-now-button");

    if (button) {
        button.disabled = true;
        button.textContent = "Running...";
    }

    showNotification(
        "Tracker run started.",
        "success"
    );

    try {
        const response = await fetch(
            "/api/run",
            {
                method: "POST",
                headers: {
                    "Accept": "application/json"
                }
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail ||
                data.error ||
                "Tracker run failed."
            );
        }

        showNotification(
            "Tracker run completed.",
            "success"
        );

        window.setTimeout(() => {
            window.location.reload();
        }, 700);

    } catch (error) {
        console.error(error);

        showNotification(
            error.message ||
            "Unable to run tracker.",
            "error"
        );

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

function showNotification(
    message,
    type = "success"
) {
    const area =
        document.getElementById(
            "notification-area"
        );

    if (!area) {
        return;
    }

    const notification =
        document.createElement("div");

    notification.className =
        `notification ${type}`;

    notification.textContent = message;

    area.appendChild(notification);

    window.setTimeout(() => {
        notification.remove();
    }, 4500);
}


/* ============================================================
   Shared API helpers
   ============================================================ */

async function apiGet(url) {
    const response =
        await fetch(url, {
            headers: {
                "Accept": "application/json"
            }
        });

    const data =
        await response.json();

    if (!response.ok) {
        throw new Error(
            data.detail ||
            data.error ||
            `Request failed: ${response.status}`
        );
    }

    return data;
}


async function apiPost(
    url,
    body = null
) {
    const options = {
        method: "POST",
        headers: {
            "Accept": "application/json"
        }
    };

    if (body !== null) {
        options.headers[
            "Content-Type"
        ] = "application/json";

        options.body =
            JSON.stringify(body);
    }

    const response =
        await fetch(url, options);

    const data =
        await response.json();

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

    const date =
        new Date(value);

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

    const number =
        Number(value);

    if (Number.isNaN(number)) {
        return String(value);
    }

    return "₹" +
        number.toLocaleString(
            "en-IN",
            {
                maximumFractionDigits: 2
            }
        );
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
   Periodic status refresh
   ============================================================ */

async function refreshGlobalStatus() {
    try {
        const data =
            await apiGet("/api/status");

        const dot =
            document.getElementById(
                "sidebar-status-dot"
            );

        const text =
            document.getElementById(
                "sidebar-status-text"
            );

        if (!dot || !text) {
            return;
        }

        const running =
            data.running === true ||
            data.status === "running";

        if (running) {
            dot.className =
                "status-dot status-online";

            text.textContent =
                "Running";
        } else {
            dot.className =
                "status-dot status-online";

            text.textContent =
                data.scheduler_running === false
                    ? "Scheduler stopped"
                    : "Monitoring";
        }

    } catch (error) {
        console.debug(
            "Status refresh failed:",
            error
        );
    }
}


document.addEventListener(
    "DOMContentLoaded",
    () => {
        refreshGlobalStatus();

        window.setInterval(
            refreshGlobalStatus,
            30000
        );
    }
);