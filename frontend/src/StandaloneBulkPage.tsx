import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

type BulkProvider = {
  slug: string;
  name: string;
};

type BulkMountContext = {
  pluginSlug: string;
  previewUrl: string;
  applyUrl: string;
  csrfToken: string;
  providers: BulkProvider[];
};

type BulkResult = {
  provider_slug: string;
  provider_name: string;
  part_id: number;
  updated: string[];
  skipped: string[];
  errors: string[];
};

type BulkResponse = {
  results: BulkResult[];
  summary: {
    requested_parts: number;
    provider_count: number;
    operations: number;
    failed: number;
    succeeded: number;
  };
};

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: '#101418',
    color: '#eef2f7',
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    padding: '32px 20px 48px',
  },
  shell: {
    maxWidth: '1080px',
    margin: '0 auto',
  },
  hero: {
    display: 'grid',
    gap: '8px',
    marginBottom: '24px',
  },
  eyebrow: {
    fontSize: '0.8rem',
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: '#79c0ff',
  },
  title: {
    margin: 0,
    fontSize: 'clamp(2rem, 4vw, 3.2rem)',
    lineHeight: 1.05,
  },
  subtitle: {
    margin: 0,
    color: '#a9b4c2',
    maxWidth: '54rem',
  },
  grid: {
    display: 'grid',
    gap: '20px',
    gridTemplateColumns: 'minmax(280px, 340px) minmax(0, 1fr)',
  },
  panel: {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '18px',
    padding: '20px',
    boxShadow: '0 24px 60px rgba(0,0,0,0.22)',
    backdropFilter: 'blur(16px)',
  },
  sectionTitle: {
    margin: '0 0 12px',
    fontSize: '0.95rem',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: '#8ea3bc',
  },
  textarea: {
    width: '100%',
    minHeight: '220px',
    borderRadius: '14px',
    border: '1px solid rgba(255,255,255,0.12)',
    background: '#0c1015',
    color: '#f4f8fb',
    padding: '14px 16px',
    resize: 'vertical',
  },
  providerList: {
    display: 'grid',
    gap: '10px',
  },
  providerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '10px 12px',
    borderRadius: '12px',
    background: 'rgba(255,255,255,0.03)',
  },
  actions: {
    display: 'flex',
    gap: '12px',
    flexWrap: 'wrap',
    marginTop: '18px',
  },
  button: {
    borderRadius: '999px',
    border: 0,
    cursor: 'pointer',
    padding: '11px 18px',
    fontWeight: 700,
  },
  buttonPrimary: {
    background: '#2f81f7',
    color: '#fff',
  },
  buttonGhost: {
    background: 'rgba(255,255,255,0.08)',
    color: '#fff',
  },
  summaryGrid: {
    display: 'grid',
    gap: '12px',
    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
    marginBottom: '18px',
  },
  summaryCard: {
    padding: '14px 16px',
    borderRadius: '14px',
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.08)',
  },
  resultCard: {
    padding: '16px',
    borderRadius: '14px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    marginBottom: '12px',
  },
  muted: {
    color: '#9aa7b5',
  },
  success: {
    color: '#4ad295',
  },
  danger: {
    color: '#ff7b72',
  },
};

function parsePartIds(input: string): number[] {
  return Array.from(
    new Set(
      input
        .split(/[\s,]+/)
        .map((token) => Number(token.trim()))
        .filter((value) => Number.isInteger(value) && value > 0)
    )
  );
}

function BulkPage({ mountContext }: { mountContext: BulkMountContext }) {
  const [rawPartIds, setRawPartIds] = useState<string>('');
  const [selectedProviders, setSelectedProviders] = useState<string[]>(
    mountContext.providers.map((provider) => provider.slug)
  );
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<BulkResponse | null>(null);

  const parsedPartIds = useMemo(() => parsePartIds(rawPartIds), [rawPartIds]);

  const toggleProvider = (providerSlug: string) => {
    setSelectedProviders((current) => (
      current.includes(providerSlug)
        ? current.filter((value) => value !== providerSlug)
        : [...current, providerSlug]
    ));
  };

  const runBulk = async (url: string) => {
    setLoading(true);
    setError(null);

    try {
      const result = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': mountContext.csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          part_ids: parsedPartIds,
          provider_slugs: selectedProviders,
        }),
      });

      const payload = await result.json();
      if (!result.ok) {
        throw new Error(payload.detail ?? `HTTP ${result.status}`);
      }

      setResponse(payload as BulkResponse);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.page}>
      <div style={styles.shell}>
        <header style={styles.hero}>
          <div style={styles.eyebrow}>Supplier Part Import</div>
          <h1 style={styles.title}>Bulk Enrich</h1>
          <p style={styles.subtitle}>
            Preview or apply missing data across many parts at once. Paste part IDs, choose providers,
            and run enrichment in a controlled batch.
          </p>
        </header>

        <div style={styles.grid}>
          <section style={styles.panel}>
            <h2 style={styles.sectionTitle}>Part IDs</h2>
            <textarea
              style={styles.textarea}
              value={rawPartIds}
              onChange={(event) => setRawPartIds(event.target.value)}
              placeholder="Paste part IDs separated by commas, spaces, or new lines"
            />
            <p style={styles.muted}>
              Parsed IDs: <strong>{parsedPartIds.length}</strong>
            </p>

            <h2 style={styles.sectionTitle}>Providers</h2>
            <div style={styles.providerList}>
              {mountContext.providers.map((provider) => (
                <label key={provider.slug} style={styles.providerRow}>
                  <input
                    type="checkbox"
                    checked={selectedProviders.includes(provider.slug)}
                    onChange={() => toggleProvider(provider.slug)}
                  />
                  <span>{provider.name}</span>
                </label>
              ))}
            </div>

            <div style={styles.actions}>
              <button
                style={{ ...styles.button, ...styles.buttonGhost }}
                disabled={loading || parsedPartIds.length === 0 || selectedProviders.length === 0}
                onClick={() => {
                  void runBulk(mountContext.previewUrl);
                }}
              >
                {loading ? 'Working…' : 'Preview changes'}
              </button>
              <button
                style={{ ...styles.button, ...styles.buttonPrimary }}
                disabled={loading || parsedPartIds.length === 0 || selectedProviders.length === 0}
                onClick={() => {
                  void runBulk(mountContext.applyUrl);
                }}
              >
                {loading ? 'Working…' : 'Apply changes'}
              </button>
            </div>
          </section>

          <section style={styles.panel}>
            <h2 style={styles.sectionTitle}>Results</h2>

            {error && <p style={styles.danger}>{error}</p>}
            {!error && !response && <p style={styles.muted}>Run a preview or apply request to see results.</p>}

            {response && (
              <>
                <div style={styles.summaryGrid}>
                  <div style={styles.summaryCard}>
                    <div style={styles.muted}>Requested parts</div>
                    <strong>{response.summary.requested_parts}</strong>
                  </div>
                  <div style={styles.summaryCard}>
                    <div style={styles.muted}>Providers</div>
                    <strong>{response.summary.provider_count}</strong>
                  </div>
                  <div style={styles.summaryCard}>
                    <div style={styles.muted}>Succeeded</div>
                    <strong style={styles.success}>{response.summary.succeeded}</strong>
                  </div>
                  <div style={styles.summaryCard}>
                    <div style={styles.muted}>Failed</div>
                    <strong style={styles.danger}>{response.summary.failed}</strong>
                  </div>
                </div>

                {response.results.map((result) => (
                  <article key={`${result.part_id}-${result.provider_slug}`} style={styles.resultCard}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                      <strong>Part #{result.part_id}</strong>
                      <span style={styles.muted}>{result.provider_name}</span>
                    </div>

                    {result.updated.length > 0 && (
                      <p style={styles.success}>Updated: {result.updated.join(', ')}</p>
                    )}
                    {result.skipped.length > 0 && (
                      <p style={styles.muted}>Skipped: {result.skipped.join(', ')}</p>
                    )}
                    {result.errors.length > 0 && (
                      <p style={styles.danger}>Errors: {result.errors.join('; ')}</p>
                    )}
                    {result.updated.length === 0 && result.skipped.length === 0 && result.errors.length === 0 && (
                      <p style={styles.muted}>No changes reported.</p>
                    )}
                  </article>
                ))}
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export function renderStandaloneBulkPage(target: HTMLElement, mountContext: BulkMountContext) {
  createRoot(target).render(<BulkPage mountContext={mountContext} />);
}

// Self-mount: when the bundle is inlined in the server-rendered HTML the
// template sets window.__BULK_MOUNT_CONTEXT__ before this script executes.
if (typeof window !== 'undefined') {
  const ctx = (window as unknown as Record<string, unknown>).__BULK_MOUNT_CONTEXT__;
  if (ctx) {
    const target = document.getElementById('inventree-import-plugin-bulk-root');
    if (target) {
      renderStandaloneBulkPage(target, ctx as BulkMountContext);
    }
  }
}
