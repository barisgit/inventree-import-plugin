/**
 * InvenTree Part-detail panel: Enrich from supplier.
 *
 * Exported entry point consumed by InvenTree's UserInterfaceMixin:
 *   source: 'enrich_panel.js:renderEnrichPanel'
 *
 * @param {HTMLElement} target  - DOM element to render into
 * @param {object}      data    - Panel context provided by InvenTree
 *   data.model          - e.g. 'part'
 *   data.id             - Part primary key
 *   data.context        - Plugin-provided context dict
 *     .plugin_slug      - The plugin's registered slug
 *     .supplier_name    - Human-readable supplier name ('Mouser' or 'LCSC')
 */
export function renderEnrichPanel(target, data) {
    if (!(target instanceof HTMLElement) || !data || data.model !== 'part') {
        return;
    }

    _clearChildren(target);

    const { plugin_slug: pluginSlug, supplier_name: supplierName } = data.context ?? {};
    const partId = data.id;

    const container = document.createElement('div');
    container.style.cssText = 'padding: 12px;';

    const button = document.createElement('button');
    button.textContent = `Enrich from ${supplierName}`;
    button.className = 'btn btn-sm btn-primary';
    button.style.marginBottom = '12px';

    const output = document.createElement('div');
    output.setAttribute('aria-live', 'polite');

    container.appendChild(button);
    container.appendChild(output);
    target.appendChild(container);

    if (!pluginSlug || !supplierName || !partId) {
        button.disabled = true;
        _renderError(output, 'Panel context is incomplete. Refresh the page and try again.');
        return;
    }

    button.addEventListener('click', async () => {
        button.disabled = true;
        button.textContent = 'Enriching\u2026';
        _clearChildren(output);

        try {
            const url = `/plugin/${pluginSlug}/enrich/${partId}/`;
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': _getCsrfToken(),
                },
            });

            const result = await response.json();

            if (!response.ok) {
                _renderError(output, result.detail ?? `HTTP ${response.status}`);
            } else {
                _renderResult(output, result);
            }
        } catch (err) {
            _renderError(output, String(err));
        } finally {
            button.disabled = false;
            button.textContent = `Enrich from ${supplierName}`;
        }
    });
}

/**
 * Read the Django CSRF token from cookies.
 * @returns {string}
 */
function _getCsrfToken() {
    const match = document.cookie.split(';')
        .map(c => c.trim())
        .find(c => c.startsWith('csrftoken='));
    return match ? match.split('=')[1] : '';
}

/**
 * Remove all children from an element.
 * @param {HTMLElement} el
 */
function _clearChildren(el) {
    while (el.firstChild) {
        el.removeChild(el.firstChild);
    }
}

/**
 * Append a text line element to a container.
 * @param {HTMLElement} parent
 * @param {string} text
 * @param {string|null} [color]
 * @returns {HTMLElement}
 */
function _appendLine(parent, text, color) {
    const p = document.createElement('p');
    p.style.margin = '2px 0';
    if (color) {
        p.style.color = color;
    }
    p.textContent = text;
    parent.appendChild(p);
    return p;
}

/**
 * Render a structured result dict into the output element.
 * @param {HTMLElement} el
 * @param {{ updated: string[], skipped: string[], errors: string[] }} result
 */
function _renderResult(el, result) {
    const { updated = [], errors = [] } = result;

    if (updated.length > 0) {
        _appendLine(el, `Updated (${updated.length}): ${updated.join(', ')}`);
    } else {
        _appendLine(el, 'Nothing to update — all fields already populated.');
    }

    if (errors.length > 0) {
        _appendLine(
            el,
            `Errors (${errors.length}): ${errors.join('; ')}`,
            'var(--bs-danger, #dc3545)'
        );
    }
}

/**
 * Render an error message into the output element.
 * @param {HTMLElement} el
 * @param {string} message
 */
function _renderError(el, message) {
    _appendLine(el, `Error: ${message}`, 'var(--bs-danger, #dc3545)');
}
