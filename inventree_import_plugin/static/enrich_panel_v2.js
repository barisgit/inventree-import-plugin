const PANEL_KEY_ATTR = 'data-enrich-panel-key';
const MODAL_KEY_ATTR = 'data-enrich-modal-key';
const ROOT_KEY_ATTR = 'data-enrich-root-key';

export function renderEnrichPanel(target, data) {
    if (!(target instanceof HTMLElement) || !data || data.model !== 'part') {
        return;
    }

    const { plugin_slug: pluginSlug, supplier_name: supplierName } = data.context ?? {};
    const partId = data.id;

    if (!pluginSlug || !supplierName || !partId) {
        _clearChildren(target);
        _appendMessage(target, 'Panel context is incomplete. Refresh the page and try again.', _dangerColor());
        return;
    }

    const panelKey = `${pluginSlug}:${partId}`;

    _removeStaleRoots(panelKey, target);
    _clearChildren(target);
    target.setAttribute(PANEL_KEY_ATTR, panelKey);

    const root = document.createElement('div');
    root.setAttribute(ROOT_KEY_ATTR, panelKey);
    target.appendChild(root);

    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = `Enrich from ${supplierName}`;
    button.className = 'btn btn-sm btn-primary';
    button.addEventListener('click', () => _openPreviewModal({ panelKey, pluginSlug, supplierName, partId }));

    root.appendChild(button);
}

async function _openPreviewModal(ctx) {
    const modal = _createModalShell(ctx);
    const body = modal.querySelector('[data-role="body"]');

    _renderLoading(body, `Loading ${ctx.supplierName} preview…`);

    try {
        const response = await fetch(_enrichUrl(ctx), {
            headers: { 'Accept': 'application/json' },
        });
        const preview = await response.json();

        if (!response.ok) {
            _renderErrorState(modal, ctx, preview.detail ?? `HTTP ${response.status}`);
            return;
        }

        _renderPreviewState(modal, ctx, preview);
    } catch (error) {
        _renderErrorState(modal, ctx, String(error));
    }
}

function _renderPreviewState(modal, ctx, preview) {
    const body = modal.querySelector('[data-role="body"]');
    const footer = modal.querySelector('[data-role="footer"]');
    const { updated = [], skipped = [], errors = [] } = preview;

    _clearChildren(body);
    _clearChildren(footer);

    if (updated.length === 0 && skipped.length === 0 && errors.length === 0) {
        _appendMessage(body, 'Nothing to update — all fields already look complete.');
    } else {
        if (updated.length > 0) {
            _appendSection(body, 'Would update', updated, _successColor());
        }
        if (skipped.length > 0) {
            _appendSection(body, 'Already set', skipped, _mutedColor());
        }
        if (errors.length > 0) {
            _appendSection(body, 'Warnings', errors, _dangerColor());
        }
    }

    if (updated.length > 0) {
        footer.appendChild(_createButton('Apply changes', 'btn btn-sm btn-primary', async () => {
            await _applyChanges(modal, ctx);
        }));
    }

    footer.appendChild(_createButton('Close', 'btn btn-sm btn-outline-secondary', () => {
        modal.remove();
    }));
}

async function _applyChanges(modal, ctx) {
    const body = modal.querySelector('[data-role="body"]');
    const footer = modal.querySelector('[data-role="footer"]');

    _clearChildren(body);
    _clearChildren(footer);
    _renderLoading(body, 'Applying changes…');

    try {
        const response = await fetch(_enrichUrl(ctx), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': _getCsrfToken(),
            },
        });
        const result = await response.json();

        _clearChildren(body);

        if (!response.ok) {
            _appendMessage(body, `Error: ${result.detail ?? `HTTP ${response.status}`}`, _dangerColor());
        } else {
            const { updated = [], skipped = [], errors = [] } = result;

            if (updated.length > 0) {
                _appendSection(body, 'Updated', updated, _successColor());
            } else {
                _appendMessage(body, 'Nothing was updated.');
            }

            if (skipped.length > 0) {
                _appendSection(body, 'Skipped', skipped, _mutedColor());
            }

            if (errors.length > 0) {
                _appendSection(body, 'Errors', errors, _dangerColor());
            }
        }
    } catch (error) {
        _clearChildren(body);
        _appendMessage(body, `Error: ${String(error)}`, _dangerColor());
    }

    footer.appendChild(_createButton('Close', 'btn btn-sm btn-outline-secondary', () => {
        modal.remove();
    }));
}

function _renderErrorState(modal, ctx, message) {
    const body = modal.querySelector('[data-role="body"]');
    const footer = modal.querySelector('[data-role="footer"]');

    _clearChildren(body);
    _clearChildren(footer);
    _appendMessage(body, `Error: ${message}`, _dangerColor());
    footer.appendChild(_createButton('Close', 'btn btn-sm btn-outline-secondary', () => {
        modal.remove();
    }));
}

function _createModalShell(ctx) {
    _removeStaleModal(ctx.panelKey);

    const overlay = document.createElement('div');
    overlay.setAttribute(MODAL_KEY_ATTR, ctx.panelKey);
    overlay.style.cssText = [
        'position:fixed',
        'inset:0',
        'z-index:1055',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'padding:24px',
        'background:rgba(0,0,0,0.55)',
    ].join(';');

    const panel = document.createElement('div');
    panel.style.cssText = [
        'width:min(720px, 100%)',
        'max-height:min(80vh, 720px)',
        'overflow:auto',
        'border-radius:12px',
        'border:1px solid var(--bs-border-color, rgba(255,255,255,0.12))',
        'background:var(--bs-body-bg, #212529)',
        'color:var(--bs-body-color, #f8f9fa)',
        'box-shadow:0 1rem 3rem rgba(0,0,0,0.45)',
    ].join(';');

    const header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--bs-border-color, rgba(255,255,255,0.12));';
    const title = document.createElement('strong');
    title.textContent = `${ctx.supplierName} enrich preview`;
    header.appendChild(title);
    header.appendChild(_createButton('×', 'btn btn-sm btn-link', () => {
        overlay.remove();
    }));

    const body = document.createElement('div');
    body.setAttribute('data-role', 'body');
    body.style.cssText = 'padding:16px 18px;';

    const footer = document.createElement('div');
    footer.setAttribute('data-role', 'footer');
    footer.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;padding:0 18px 16px;';

    panel.appendChild(header);
    panel.appendChild(body);
    panel.appendChild(footer);
    overlay.appendChild(panel);
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) {
            overlay.remove();
        }
    });

    document.body.appendChild(overlay);
    return overlay;
}

function _createButton(label, className, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.className = className;
    button.addEventListener('click', onClick);
    return button;
}

function _appendSection(parent, title, items, color) {
    const heading = document.createElement('div');
    heading.textContent = title;
    heading.style.cssText = `margin:0 0 6px;font-weight:600;color:${color};`;
    parent.appendChild(heading);

    const list = document.createElement('ul');
    list.style.cssText = 'margin:0 0 14px 18px;padding:0;';

    for (const item of items) {
        const row = document.createElement('li');
        row.textContent = item;
        list.appendChild(row);
    }

    parent.appendChild(list);
}

function _appendMessage(parent, text, color = 'var(--bs-body-color, #f8f9fa)') {
    const message = document.createElement('p');
    message.style.cssText = `margin:0;color:${color};`;
    message.textContent = text;
    parent.appendChild(message);
}

function _renderLoading(parent, text) {
    _clearChildren(parent);
    _appendMessage(parent, text, _mutedColor());
}

function _enrichUrl(ctx) {
    return `/plugin/${ctx.pluginSlug}/enrich/${ctx.partId}/`;
}

function _removeStaleRoots(panelKey, currentTarget) {
    for (const node of document.querySelectorAll(`[${ROOT_KEY_ATTR}="${panelKey}"]`)) {
        if (!currentTarget.contains(node)) {
            node.remove();
        }
    }
}

function _removeStaleModal(panelKey) {
    for (const node of document.querySelectorAll(`[${MODAL_KEY_ATTR}="${panelKey}"]`)) {
        node.remove();
    }
}

function _clearChildren(element) {
    while (element.firstChild) {
        element.removeChild(element.firstChild);
    }
}

function _getCsrfToken() {
    const match = document.cookie.split(';')
        .map((cookie) => cookie.trim())
        .find((cookie) => cookie.startsWith('csrftoken='));
    return match ? match.split('=')[1] : '';
}

function _successColor() {
    return 'var(--bs-success, #198754)';
}

function _dangerColor() {
    return 'var(--bs-danger, #dc3545)';
}

function _mutedColor() {
    return 'var(--bs-secondary-color, #adb5bd)';
}
