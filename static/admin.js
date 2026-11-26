(() => {
    const root = document.querySelector("#panel-root");
    const formatter = new Intl.NumberFormat("en-PK", { maximumFractionDigits: 3 });
    let opener;
    let pendingPanel;

    function setSteps(form) {
        const units = form.querySelector("[data-unit-select]");
        if (!units) return;
        const step = units.selectedOptions[0]?.dataset.step || "1";
        form.querySelectorAll("[data-stock-field]").forEach((input) => { input.step = step; });
    }

    function renderQuantity(ticks, unit) {
        const label = unit === "piece" && ticks !== 1000 ? "pieces" : unit;
        return formatter.format(ticks / 1000) + " " + label;
    }

    function renderStock(form) {
        const preview = form.querySelector("[data-stock-preview]");
        if (!preview) return;
        const amount = form.elements.amount;
        const result = preview.querySelector("[data-result]");
        const current = Math.round(Number(preview.dataset.current) * 1000);
        const adding = preview.dataset.direction === "add";
        if (adding) amount.max = String((9999999999999 - current) / 1000);
        const change = Math.round(amount.valueAsNumber * 1000);
        const after = adding ? current + change : current - change;
        result.textContent = amount.value && amount.validity.valid
            ? renderQuantity(after, preview.dataset.unit)
            : "—";
    }

    function showPanel(panel) {
        if (typeof panel.showModal !== "function") return;
        panel.removeAttribute("open");
        panel.showModal();
        const form = panel.querySelector("form");
        if (!form) return;
        setSteps(form);
        renderStock(form);
        const firstInvalid = form.querySelector("[aria-invalid='true']");
        const firstInput = form.querySelector("input:not([type='hidden']):not([readonly])");
        (firstInvalid || firstInput)?.focus();
    }

    function closePanel(panel) {
        pendingPanel?.abort();
        panel.close();
        panel.remove();
        if (new URL(location.href).searchParams.has("action")) {
            history.replaceState(null, "", panel.dataset.returnUrl);
        }
        const target = opener?.isConnected ? opener : document.querySelector(".page-header [data-panel-link]");
        target?.focus();
        opener = undefined;
    }

    async function fetchPanel(link) {
        const previous = root.querySelector("dialog[data-panel]");
        if (!previous) opener = link;
        pendingPanel?.abort();
        const controller = new AbortController();
        pendingPanel = controller;
        try {
            const response = await fetch(link.href, {
                headers: { "X-Inventory-Panel": "1" },
                signal: controller.signal,
            });
            const page = new DOMParser().parseFromString(await response.text(), "text/html");
            const panel = page.querySelector("dialog[data-panel]");
            if (!panel) {
                location.assign(link.href);
                return;
            }
            previous?.close();
            root.replaceChildren(panel);
            showPanel(panel);
        } catch (error) {
            if (error.name !== "AbortError") location.assign(link.href);
        }
    }

    document.addEventListener("click", (event) => {
        const dismiss = event.target.closest("[data-dismiss-notice]");
        if (dismiss) dismiss.closest(".notification").remove();

        const close = event.target.closest("[data-panel-close]");
        const panel = close?.closest("dialog[data-panel]");
        if (panel?.matches(":modal")) {
            event.preventDefault();
            closePanel(panel);
            return;
        }

        const link = event.target.closest("[data-panel-link]");
        if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        if (typeof HTMLDialogElement === "undefined" || !HTMLDialogElement.prototype.showModal) return;
        event.preventDefault();
        fetchPanel(link);
    });

    root.addEventListener("cancel", (event) => {
        event.preventDefault();
        closePanel(event.target);
    }, true);
    root.addEventListener("input", (event) => {
        const form = event.target.closest("[data-inventory-form]");
        if (!form) return;
        setSteps(form);
        renderStock(form);
    });
    root.addEventListener("submit", (event) => {
        const form = event.target;
        if (form.getAttribute("aria-busy") === "true") {
            event.preventDefault();
            return;
        }
        form.setAttribute("aria-busy", "true");
    });
    window.addEventListener("pageshow", (event) => {
        if (!event.persisted) return;
        root.querySelector("form[aria-busy='true']")?.removeAttribute("aria-busy");
    });

    const panel = root.querySelector("dialog[data-panel]");
    if (panel) showPanel(panel);

    const url = new URL(location.href);
    if (url.searchParams.has("notice")) {
        url.searchParams.delete("notice");
        history.replaceState(null, "", url);
    }
})();
