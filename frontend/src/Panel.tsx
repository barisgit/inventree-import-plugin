import { useCallback, useEffect, useMemo, useState } from 'react';
import type { InvenTreePluginContext } from '@inventreedb/ui';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Chip,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';

/* ------------------------------------------------------------------ */
/*  Shared types                                                      */
/* ------------------------------------------------------------------ */

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

type BulkSummary = {
  requested_parts: number;
  provider_count: number;
  operations: number;
  failed: number;
  succeeded: number;
};

type BulkResponse = {
  results: EnrichResult[];
  summary: BulkSummary;
};

type PanelContextData = {
  plugin_slug?: string;
};

type CategoryPart = {
  pk: number;
  name: string;
  IPN: string | null;
  description: string;
};

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

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

function pluginApi(pluginSlug: string, path: string): string {
  return `/plugin/${pluginSlug}/api/${path}`;
}

/* ------------------------------------------------------------------ */
/*  Single-part enrichment panel (part detail page)                   */
/* ------------------------------------------------------------------ */

function EnrichPanel({ context }: { context: InvenTreePluginContext }) {
  const panelContext = (context.context ?? {}) as PanelContextData;
  const pluginSlug = panelContext.plugin_slug ?? '';
  const partId = Number(context.id ?? 0);

  const [providerState, setProviderState] = useState<ProviderStateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<EnrichResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);

  const fetchUrl = useMemo(() => {
    if (!pluginSlug || !partId) return null;
    return pluginApi(pluginSlug, `part/${partId}/providers/`);
  }, [pluginSlug, partId]);

  useEffect(() => {
    if (!fetchUrl) {
      setError('Panel context is incomplete.');
      setLoading(false);
      return;
    }

    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await context.api.get<ProviderStateResponse>(fetchUrl);
        setProviderState(response.data);
      } catch (err) {
        setError(String(err));
      } finally {
        setLoading(false);
      }
    };

    void run();
  }, [context.api, fetchUrl]);

  const previewProvider = async (provider: ProviderState) => {
    setPreviewLoading(true);
    setPreviewResult(null);
    try {
      const response = await context.api.get<EnrichResult>(
        pluginApi(pluginSlug, `part/${partId}/preview/${provider.slug}/`)
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
    if (!previewResult) return;
    setApplyLoading(true);
    try {
      const response = await context.api.post<EnrichResult>(
        pluginApi(pluginSlug, `part/${partId}/apply/${previewResult.provider_slug}/`)
      );
      setPreviewResult(response.data);
      if (fetchUrl) {
        const stateResponse = await context.api.get<ProviderStateResponse>(fetchUrl);
        setProviderState(stateResponse.data);
      }
    } catch (err) {
      setPreviewResult({ ...previewResult, updated: [], skipped: [], errors: [String(err)] });
    } finally {
      setApplyLoading(false);
    }
  };

  if (loading) {
    return (
      <Paper p="md">
        <Group><Loader size="sm" /><Text>Loading enrich providers...</Text></Group>
      </Paper>
    );
  }

  if (error) {
    return <Alert color="red" title="Unable to load enrich state">{error}</Alert>;
  }

  return (
    <>
      <Stack gap="md">
        <Stack gap={4}>
          <Title order={4}>Supplier Enrichment</Title>
          <Text c="dimmed" size="sm">
            Preview and apply missing part data from configured supplier links.
          </Text>
        </Stack>

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
                  onClick={() => { void previewProvider(provider); }}
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
        onClose={() => { if (!previewLoading && !applyLoading) setPreviewResult(null); }}
        title={previewResult ? `${previewResult.provider_name} preview` : 'Loading preview'}
        size="lg"
      >
        {previewLoading && (
          <Group><Loader size="sm" /><Text>Loading preview...</Text></Group>
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
                onClick={() => { void applyProvider(); }}
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

/* ------------------------------------------------------------------ */
/*  Category bulk enrichment panel (partcategory page)                */
/* ------------------------------------------------------------------ */

const PARTS_PAGE_LIMIT = 500;

function CategoryEnrichPanel({ context }: { context: InvenTreePluginContext }) {
  const panelContext = (context.context ?? {}) as PanelContextData;
  const pluginSlug = panelContext.plugin_slug ?? '';
  const categoryId = Number(context.id ?? 0);

  /* -- data state -- */
  const [parts, setParts] = useState<CategoryPart[]>([]);
  const [partsLoading, setPartsLoading] = useState(true);
  const [partsError, setPartsError] = useState<string | null>(null);

  const [providers, setProviders] = useState<ProviderState[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);

  /* -- selection state -- */
  const [selectedPartIds, setSelectedPartIds] = useState<Set<number>>(new Set());
  const [selectedProviderSlugs, setSelectedProviderSlugs] = useState<string[]>([]);

  /* -- bulk operation state -- */
  const [bulkResult, setBulkResult] = useState<BulkResponse | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkMode, setBulkMode] = useState<'preview' | 'apply'>('preview');

  /* -- fetch parts in category -- */
  useEffect(() => {
    if (!categoryId) {
      setPartsError('No category ID available.');
      setPartsLoading(false);
      return;
    }

    const run = async () => {
      setPartsLoading(true);
      setPartsError(null);
      try {
        const response = await context.api.get<CategoryPart[]>('/api/part/', {
          params: { category: categoryId, limit: PARTS_PAGE_LIMIT, offset: 0 },
        });
        const data = Array.isArray(response.data)
          ? response.data
          : (response.data as unknown as { results: CategoryPart[] }).results ?? [];
        setParts(data);
      } catch (err) {
        setPartsError(String(err));
      } finally {
        setPartsLoading(false);
      }
    };

    void run();
  }, [context.api, categoryId]);

  /* -- fetch available providers (use first part or a dedicated endpoint) -- */
  useEffect(() => {
    if (!pluginSlug || parts.length === 0) {
      setProvidersLoading(false);
      return;
    }

    const run = async () => {
      setProvidersLoading(true);
      try {
        const response = await context.api.get<ProviderStateResponse>(
          pluginApi(pluginSlug, `part/${parts[0].pk}/providers/`)
        );
        setProviders(response.data.providers.filter((p) => p.enabled && p.configured));
      } catch {
        setProviders([]);
      } finally {
        setProvidersLoading(false);
      }
    };

    void run();
  }, [context.api, pluginSlug, parts]);

  /* -- row selection helpers -- */
  const allSelected = parts.length > 0 && selectedPartIds.size === parts.length;
  const someSelected = selectedPartIds.size > 0 && !allSelected;

  const toggleAll = useCallback(() => {
    setSelectedPartIds(allSelected ? new Set() : new Set(parts.map((p) => p.pk)));
  }, [allSelected, parts]);

  const togglePart = useCallback((pk: number) => {
    setSelectedPartIds((prev) => {
      const next = new Set(prev);
      if (next.has(pk)) next.delete(pk);
      else next.add(pk);
      return next;
    });
  }, []);

  /* -- bulk operations -- */
  const canOperate = selectedPartIds.size > 0 && selectedProviderSlugs.length > 0;

  const runBulk = useCallback(async (mode: 'preview' | 'apply') => {
    if (!canOperate) return;
    setBulkLoading(true);
    setBulkMode(mode);
    setBulkResult(null);
    try {
      const endpoint = mode === 'preview' ? 'bulk/preview/' : 'bulk/apply/';
      const response = await context.api.post<BulkResponse>(
        pluginApi(pluginSlug, endpoint),
        { part_ids: Array.from(selectedPartIds), provider_slugs: selectedProviderSlugs },
      );
      setBulkResult(response.data);
    } catch (err) {
      setBulkResult({
        results: [],
        summary: { requested_parts: selectedPartIds.size, provider_count: selectedProviderSlugs.length, operations: 0, failed: 1, succeeded: 0 },
      });
    } finally {
      setBulkLoading(false);
    }
  }, [canOperate, context.api, pluginSlug, selectedPartIds, selectedProviderSlugs]);

  /* -- loading state -- */
  if (partsLoading) {
    return (
      <Paper p="md">
        <Group><Loader size="sm" /><Text>Loading parts in this category...</Text></Group>
      </Paper>
    );
  }

  if (partsError) {
    return <Alert color="red" title="Failed to load parts">{partsError}</Alert>;
  }

  if (parts.length === 0) {
    return (
      <Alert color="gray" title="No parts">
        This category contains no parts to enrich.
      </Alert>
    );
  }

  return (
    <>
      <Stack gap="md">
        <Stack gap={4}>
          <Title order={4}>Category Enrichment</Title>
          <Text c="dimmed" size="sm">
            Select parts and providers, then preview or apply supplier data in bulk.
          </Text>
        </Stack>

        <Divider />

        {/* Provider chip selector */}
        <Stack gap="xs">
          <Text fw={600} size="sm">Providers</Text>
          {providersLoading ? (
            <Group><Loader size="xs" /><Text size="sm" c="dimmed">Loading providers...</Text></Group>
          ) : providers.length === 0 ? (
            <Text size="sm" c="dimmed">No configured providers available.</Text>
          ) : (
            <Chip.Group multiple value={selectedProviderSlugs} onChange={setSelectedProviderSlugs}>
              <Group gap="xs">
                {providers.map((p) => (
                  <Chip key={p.slug} value={p.slug} variant="outline" size="sm">
                    {p.name}
                  </Chip>
                ))}
              </Group>
            </Chip.Group>
          )}
        </Stack>

        <Divider />

        {/* Parts table */}
        <Stack gap="xs">
          <Group justify="space-between" align="center">
            <Text fw={600} size="sm">
              Parts ({selectedPartIds.size} of {parts.length} selected)
            </Text>
            <Group gap="xs">
              <Tooltip label={`Preview changes for ${selectedPartIds.size} part(s)`}>
                <Button
                  size="xs"
                  variant="light"
                  disabled={!canOperate}
                  loading={bulkLoading && bulkMode === 'preview'}
                  onClick={() => { void runBulk('preview'); }}
                >
                  Preview selected
                </Button>
              </Tooltip>
              <Tooltip label={`Apply changes to ${selectedPartIds.size} part(s)`}>
                <Button
                  size="xs"
                  disabled={!canOperate}
                  loading={bulkLoading && bulkMode === 'apply'}
                  onClick={() => { void runBulk('apply'); }}
                >
                  Apply selected
                </Button>
              </Tooltip>
            </Group>
          </Group>

          <ScrollArea.Autosize mah={480}>
            <Table striped highlightOnHover withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={40}>
                    <Checkbox
                      checked={allSelected}
                      indeterminate={someSelected}
                      onChange={toggleAll}
                      aria-label="Select all parts"
                    />
                  </Table.Th>
                  <Table.Th>Name</Table.Th>
                  <Table.Th>IPN</Table.Th>
                  <Table.Th>Description</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {parts.map((part) => (
                  <Table.Tr
                    key={part.pk}
                    bg={selectedPartIds.has(part.pk) ? 'var(--mantine-primary-color-light)' : undefined}
                    style={{ cursor: 'pointer' }}
                    onClick={() => togglePart(part.pk)}
                  >
                    <Table.Td onClick={(e: React.MouseEvent) => e.stopPropagation()}>
                      <Checkbox
                        checked={selectedPartIds.has(part.pk)}
                        onChange={() => togglePart(part.pk)}
                        aria-label={`Select ${part.name}`}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" fw={500}>{part.name}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c="dimmed">{part.IPN ?? '-'}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" lineClamp={1}>{part.description}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea.Autosize>
        </Stack>
      </Stack>

      {/* Bulk results modal */}
      <Modal
        opened={bulkLoading || bulkResult !== null}
        onClose={() => { if (!bulkLoading) setBulkResult(null); }}
        title={bulkMode === 'preview' ? 'Bulk Preview Results' : 'Bulk Apply Results'}
        size="xl"
      >
        {bulkLoading && (
          <Group><Loader size="sm" /><Text>Processing...</Text></Group>
        )}
        {bulkResult && !bulkLoading && (
          <Stack gap="md">
            {/* Summary bar */}
            <Group gap="lg">
              <Badge color="blue" variant="light" size="lg">
                {bulkResult.summary.operations} operations
              </Badge>
              <Badge color="green" variant="light" size="lg">
                {bulkResult.summary.succeeded} succeeded
              </Badge>
              {bulkResult.summary.failed > 0 && (
                <Badge color="red" variant="light" size="lg">
                  {bulkResult.summary.failed} failed
                </Badge>
              )}
            </Group>

            <Divider />

            {/* Per-part results */}
            <ScrollArea.Autosize mah={400}>
              <Stack gap="sm">
                {bulkResult.results.map((result) => (
                  <Card
                    key={`${result.part_id}-${result.provider_slug}`}
                    withBorder
                    radius="sm"
                    padding="sm"
                  >
                    <Group gap="xs" mb={4}>
                      <Text size="sm" fw={600}>Part #{result.part_id}</Text>
                      <Badge size="sm" variant="dot">{result.provider_name}</Badge>
                    </Group>
                    <ResultList title="Updated" items={result.updated} color="green" />
                    <ResultList title="Skipped" items={result.skipped} color="gray" />
                    <ResultList title="Errors" items={result.errors} color="red" />
                  </Card>
                ))}

                {bulkResult.results.length === 0 && (
                  <Text c="dimmed" size="sm" ta="center">No results returned.</Text>
                )}
              </Stack>
            </ScrollArea.Autosize>

            <Group justify="flex-end">
              <Button variant="default" onClick={() => setBulkResult(null)}>
                Close
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Entry point                                                       */
/* ------------------------------------------------------------------ */

export function renderEnrichPanel(context: InvenTreePluginContext) {
  if (context.model === 'partcategory') {
    return <CategoryEnrichPanel context={context} />;
  }

  return <EnrichPanel context={context} />;
}
