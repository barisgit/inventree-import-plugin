import { useEffect, useMemo, useState } from 'react';
import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core';

type ProviderState = {
  slug: string;
  name: string;
  enabled: boolean;
  configured: boolean;
  can_enrich: boolean;
  reason: string | null;
  supplier_part_sku: string | null;
};

type ProviderStateResponse = {
  part_id: number;
  providers: ProviderState[];
  error?: string;
};

type EnrichResult = {
  provider_slug: string;
  provider_name: string;
  part_id: number;
  updated: string[];
  skipped: string[];
  errors: string[];
};

type PanelContextData = {
  plugin_slug?: string;
  bulk_url?: string;
};

function ResultList({ title, items, color }: { title: string; items: string[]; color: string }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <Stack gap="xs">
      <Text fw={700} c={color}>{title}</Text>
      <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
        {items.map((item) => (
          <li key={`${title}-${item}`}>
            <Text size="sm">{item}</Text>
          </li>
        ))}
      </ul>
    </Stack>
  );
}

function EnrichPanel({ context }: { context: InvenTreePluginContext }) {
  const panelContext = (context.context ?? {}) as PanelContextData;
  const pluginSlug = panelContext.plugin_slug ?? '';
  const partId = Number(context.id ?? 0);

  const [providerState, setProviderState] = useState<ProviderStateResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<EnrichResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);
  const [applyLoading, setApplyLoading] = useState<boolean>(false);

  const bulkUrl = panelContext.bulk_url ?? `/plugin/${pluginSlug}/bulk/`;

  const fetchState = useMemo(() => {
    if (!pluginSlug || !partId) {
      return null;
    }

    return `/plugin/${pluginSlug}/api/part/${partId}/providers/`;
  }, [pluginSlug, partId]);

  useEffect(() => {
    if (!fetchState) {
      setError('Panel context is incomplete.');
      setLoading(false);
      return;
    }

    const run = async () => {
      setLoading(true);
      setError(null);

      try {
        const response = await context.api.get<ProviderStateResponse>(fetchState);
        setProviderState(response.data);
      } catch (err) {
        setError(String(err));
      } finally {
        setLoading(false);
      }
    };

    void run();
  }, [context.api, fetchState]);

  const previewProvider = async (provider: ProviderState) => {
    setPreviewLoading(true);
    setPreviewResult(null);

    try {
      const response = await context.api.get<EnrichResult>(
        `/plugin/${pluginSlug}/api/part/${partId}/preview/${provider.slug}/`
      );
      setPreviewResult(response.data);
    } catch (err) {
      setPreviewResult({
        provider_slug: provider.slug,
        provider_name: provider.name,
        part_id: partId,
        updated: [],
        skipped: [],
        errors: [String(err)],
      });
    } finally {
      setPreviewLoading(false);
    }
  };

  const applyProvider = async () => {
    if (!previewResult) {
      return;
    }

    setApplyLoading(true);

    try {
      const response = await context.api.post<EnrichResult>(
        `/plugin/${pluginSlug}/api/part/${partId}/apply/${previewResult.provider_slug}/`
      );
      setPreviewResult(response.data);
      if (fetchState) {
        const stateResponse = await context.api.get<ProviderStateResponse>(fetchState);
        setProviderState(stateResponse.data);
      }
    } catch (err) {
      setPreviewResult({
        ...previewResult,
        updated: [],
        skipped: [],
        errors: [String(err)],
      });
    } finally {
      setApplyLoading(false);
    }
  };

  if (loading) {
    return (
      <Paper p="md">
        <Group>
          <Loader size="sm" />
          <Text>Loading enrich providers…</Text>
        </Group>
      </Paper>
    );
  }

  if (error) {
    return <Alert color="red" title="Unable to load enrich state">{error}</Alert>;
  }

  return (
    <>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Title order={4}>Supplier Enrichment</Title>
            <Text c="dimmed" size="sm">
              Preview and apply missing part data from configured supplier links.
            </Text>
          </Stack>
          <Button variant="light" onClick={() => window.location.assign(bulkUrl)}>
            Open bulk enrich
          </Button>
        </Group>

        <Divider />

        <Stack gap="sm">
          {(providerState?.providers ?? []).map((provider) => (
            <Card key={provider.slug} withBorder radius="md" padding="md">
              <Group justify="space-between" align="flex-start">
                <Stack gap={4}>
                  <Group gap="xs">
                    <Text fw={700}>{provider.name}</Text>
                    <Badge color={provider.can_enrich ? 'green' : 'gray'} variant="light">
                      {provider.can_enrich ? 'Ready' : 'Unavailable'}
                    </Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {provider.supplier_part_sku
                      ? `Linked supplier SKU: ${provider.supplier_part_sku}`
                      : provider.reason ?? 'No linked supplier part'}
                  </Text>
                </Stack>
                <Button
                  disabled={!provider.can_enrich}
                  onClick={() => {
                    void previewProvider(provider);
                  }}
                >
                  Preview changes
                </Button>
              </Group>
            </Card>
          ))}
        </Stack>
      </Stack>

      <Modal
        opened={previewLoading || previewResult !== null}
        onClose={() => {
          if (!previewLoading && !applyLoading) {
            setPreviewResult(null);
          }
        }}
        title={previewResult ? `${previewResult.provider_name} preview` : 'Loading preview'}
        size="lg"
      >
        {previewLoading && (
          <Group>
            <Loader size="sm" />
            <Text>Loading preview…</Text>
          </Group>
        )}

        {previewResult && !previewLoading && (
          <Stack gap="md">
            <ResultList title="Would update" items={previewResult.updated} color="green" />
            <ResultList title="Already set" items={previewResult.skipped} color="gray" />
            <ResultList title="Warnings" items={previewResult.errors} color="red" />

            <Group justify="flex-end">
              <Button variant="default" onClick={() => setPreviewResult(null)} disabled={applyLoading}>
                Close
              </Button>
              <Button
                onClick={() => {
                  void applyProvider();
                }}
                loading={applyLoading}
                disabled={previewResult.updated.length === 0}
              >
                Apply changes
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}

export function renderEnrichPanel(context: InvenTreePluginContext) {
  return <EnrichPanel context={context} />;
}
