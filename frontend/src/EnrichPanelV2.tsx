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

/* ---- Diff payload types (from backend _build_diff) ---- */

type DiffFieldEntry = {
  field: string;
  current: string | null;
  incoming: string | null;
};

type DiffParameterRow = {
  name: string;
  units?: string;
  current: string | null;
  incoming: string | null;
  status: 'new' | 'skipped';
};

type DiffPriceBreakRow = {
  quantity: number;
  incoming_price: number;
  incoming_currency: string;
  status: 'new' | 'skipped';
};

type DiffPayload = {
  image: DiffFieldEntry | null;
  datasheet: DiffFieldEntry | null;
  price_breaks: DiffPriceBreakRow[];
  parameters: DiffParameterRow[];
};

type EnrichResult = {
  provider_slug: string;
  provider_name: string;
  part_id: number;
  updated: string[];
  skipped: string[];
  errors: string[];
  diff?: DiffPayload;
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
/*  Key parsing & structured preview types                            */
/* ------------------------------------------------------------------ */

type ItemStatus = 'update' | 'skip' | 'error';

type ParsedItem = {
  key: string;
  label: string;
  status: ItemStatus;
};

type RichAssetItem = ParsedItem & {
  currentValue: string | null;
  incomingValue: string | null;
};

type RichParameterItem = ParsedItem & {
  currentValue: string | null;
  incomingValue: string | null;
  units?: string;
};

type RichPriceBreakItem = ParsedItem & {
  incomingPrice: number | null;
  incomingCurrency: string | null;
};

type ParsedSections = {
  assets: ParsedItem[];
  parameters: ParsedItem[];
  priceBreaks: ParsedItem[];
};

const STATUS_COLOR: Record<ItemStatus, string> = {
  update: 'green',
  skip: 'gray',
  error: 'red',
};

const STATUS_LABEL: Record<ItemStatus, string> = {
  update: 'Will update',
  skip: 'Already set',
  error: 'Error',
};

function classifyKey(raw: string): { section: keyof ParsedSections; label: string } {
  if (raw === 'image') return { section: 'assets', label: 'Part image' };
  if (raw === 'datasheet_link') return { section: 'assets', label: 'Datasheet link' };
  if (raw.startsWith('price_break:')) {
    const qty = raw.slice('price_break:'.length);
    return { section: 'priceBreaks', label: `Qty ${qty}` };
  }
  if (raw.startsWith('parameter:')) {
    const name = raw.slice('parameter:'.length);
    return { section: 'parameters', label: name };
  }
  return { section: 'assets', label: raw };
}

function parseResultKeys(result: EnrichResult): ParsedSections {
  const sections: ParsedSections = { assets: [], parameters: [], priceBreaks: [] };

  for (const key of result.updated) {
    const { section, label } = classifyKey(key);
    sections[section].push({ key, label, status: 'update' });
  }
  for (const key of result.skipped) {
    const { section, label } = classifyKey(key);
    sections[section].push({ key, label, status: 'skip' });
  }
  for (const key of result.errors) {
    sections.assets.push({ key, label: key, status: 'error' });
  }

  return sections;
}

/* ---- Diff-aware section builders ---- */

function buildAssetItems(result: EnrichResult): RichAssetItem[] {
  const diff = result.diff;
  const updatedSet = new Set(result.updated);
  const skippedSet = new Set(result.skipped);

  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.assets.map((item) => ({ ...item, currentValue: null, incomingValue: null }));
  }
  const items: RichAssetItem[] = [];
  if (diff.image) {
    const status: ItemStatus = updatedSet.has('image') ? 'update'
      : skippedSet.has('image') ? 'skip'
      : 'skip';
    items.push({
      key: 'image',
      label: 'Part image',
      status,
      currentValue: diff.image.current,
      incomingValue: diff.image.incoming,
    });
  }
  if (diff.datasheet) {
    const status: ItemStatus = updatedSet.has('datasheet_link') ? 'update'
      : skippedSet.has('datasheet_link') ? 'skip'
      : 'skip';
    items.push({
      key: 'datasheet_link',
      label: 'Datasheet link',
      status,
      currentValue: diff.datasheet.current,
      incomingValue: diff.datasheet.incoming,
    });
  }
  return items;
}

function buildParameterItems(result: EnrichResult): RichParameterItem[] {
  const diff = result.diff;
  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.parameters.map((item) => ({ ...item, currentValue: null, incomingValue: null }));
  }
  return diff.parameters.map((row) => ({
    key: `parameter:${row.name}`,
    label: row.name,
    status: row.status === 'skipped' ? 'skip' : 'update' as ItemStatus,
    currentValue: row.current,
    incomingValue: row.incoming,
    units: row.units,
  }));
}

function buildPriceBreakItems(result: EnrichResult): RichPriceBreakItem[] {
  const diff = result.diff;
  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.priceBreaks.map((item) => ({ ...item, incomingPrice: null, incomingCurrency: null }));
  }
  return diff.price_breaks.map((row) => ({
    key: `price_break:${row.quantity}`,
    label: `Qty ${row.quantity}`,
    status: row.status === 'skipped' ? 'skip' : 'update' as ItemStatus,
    incomingPrice: row.incoming_price,
    incomingCurrency: row.incoming_currency,
  }));
}

function hasAnyContent(result: EnrichResult): boolean {
  const diff = result.diff;
  if (diff) {
    return (diff.image?.incoming != null)
      || (diff.datasheet?.incoming != null)
      || diff.parameters.length > 0
      || diff.price_breaks.length > 0;
  }
  const sections = parseResultKeys(result);
  return sections.assets.length > 0
    || sections.parameters.length > 0
    || sections.priceBreaks.length > 0;
}

/* ------------------------------------------------------------------ */
/*  Structured preview components                                     */
/* ------------------------------------------------------------------ */

function StatusBadge({ status }: { status: ItemStatus }) {
  return (
    <Badge size="xs" variant="light" color={STATUS_COLOR[status]}>
      {STATUS_LABEL[status]}
    </Badge>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <Group gap="xs">
      <Text size="sm" fw={700} tt="uppercase" c="dimmed" style={{ letterSpacing: '0.04em' }}>
        {label}
      </Text>
      <Badge size="xs" variant="default" color="gray">{count}</Badge>
    </Group>
  );
}

/** Renders a clickable truncated link or "None" for diff values. */
function DiffValue({ value, side }: { value: string | null; side: 'current' | 'incoming' }) {
  if (value == null) {
    return <Text size="xs" c="dimmed" fs="italic">None</Text>;
  }
  const isUrl = value.startsWith('http');
  const display = value.length > 60 ? value.slice(0, 57) + '...' : value;
  const color = side === 'incoming' ? 'green.8' : 'dimmed';
  if (isUrl) {
    return (
      <Tooltip label={value} openDelay={300} maw={400}>
        <Text
          component="a"
          href={value}
          target="_blank"
          rel="noopener noreferrer"
          size="xs"
          c={color}
          truncate="end"
          maw={320}
          style={{ wordBreak: 'break-all', textDecoration: 'underline', cursor: 'pointer' }}
        >
          {display}
        </Text>
      </Tooltip>
    );
  }
  return <Text size="xs" c={color} style={{ wordBreak: 'break-word' }}>{display}</Text>;
}

function AssetRows({ items }: { items: RichAssetItem[] }) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  return (
    <Stack gap={4}>
      <SectionHeader label="Assets" count={items.length} />
      <Paper withBorder radius="sm" p="xs">
        <Stack gap={6}>
          {items.map((item) => (
            <Group key={item.key} justify="space-between" wrap="nowrap">
              <Text size="sm">{item.label}</Text>
              {hasRichData ? (
                <Group gap="xs" wrap="nowrap">
                  <DiffValue value={item.currentValue} side="current" />
                  <Text size="xs" c="dimmed">→</Text>
                  <DiffValue value={item.incomingValue} side="incoming" />
                  <StatusBadge status={item.status} />
                </Group>
              ) : (
                <StatusBadge status={item.status} />
              )}
            </Group>
          ))}
        </Stack>
      </Paper>
    </Stack>
  );
}

function ParameterRows({ items }: { items: RichParameterItem[] }) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  return (
    <Stack gap={4}>
      <SectionHeader label="Parameters" count={items.length} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th><Text size="xs" fw={600}>Parameter</Text></Table.Th>
            {hasRichData && <Table.Th><Text size="xs" fw={600}>Current</Text></Table.Th>}
            {hasRichData && <Table.Th><Text size="xs" fw={600}>Incoming</Text></Table.Th>}
            <Table.Th w={100}><Text size="xs" fw={600}>Status</Text></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sorted.map((item) => (
            <Table.Tr
              key={item.key}
              bg={item.status === 'update' ? 'var(--mantine-color-green-light)' : undefined}
            >
              <Table.Td>
                <Text size="sm">
                  {item.label}
                  {item.units ? <Text component="span" size="xs" c="dimmed"> [{item.units}]</Text> : null}
                </Text>
              </Table.Td>
              {hasRichData && (
                <Table.Td><DiffValue value={item.currentValue} side="current" /></Table.Td>
              )}
              {hasRichData && (
                <Table.Td><DiffValue value={item.incomingValue} side="incoming" /></Table.Td>
              )}
              <Table.Td><StatusBadge status={item.status} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function PriceBreakRows({ items }: { items: RichPriceBreakItem[] }) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.incomingPrice !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  return (
    <Stack gap={4}>
      <SectionHeader label="Price Breaks" count={items.length} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th><Text size="xs" fw={600}>Quantity</Text></Table.Th>
            {hasRichData && <Table.Th><Text size="xs" fw={600}>Incoming Price</Text></Table.Th>}
            <Table.Th w={100}><Text size="xs" fw={600}>Status</Text></Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sorted.map((item) => (
            <Table.Tr
              key={item.key}
              bg={item.status === 'update' ? 'var(--mantine-color-green-light)' : undefined}
            >
              <Table.Td><Text size="sm">{item.label}</Text></Table.Td>
              {hasRichData && (
                <Table.Td>
                  {item.incomingPrice != null ? (
                    <Text size="sm">
                      {item.incomingCurrency ? `${item.incomingCurrency} ` : ''}
                      {item.incomingPrice}
                    </Text>
                  ) : (
                    <Text size="xs" c="dimmed" fs="italic">-</Text>
                  )}
                </Table.Td>
              )}
              <Table.Td><StatusBadge status={item.status} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function StructuredPreview({ result }: { result: EnrichResult }) {
  const assetItems = useMemo(() => buildAssetItems(result), [result]);
  const parameterItems = useMemo(() => buildParameterItems(result), [result]);
  const priceBreakItems = useMemo(() => buildPriceBreakItems(result), [result]);

  if (!hasAnyContent(result)) {
    return (
      <Text size="sm" c="dimmed" ta="center" py="md">
        No changes detected from this provider.
      </Text>
    );
  }

  const updateCount = result.updated.length;
  const skipCount = result.skipped.length;
  const errorCount = result.errors.length;

  return (
    <Stack gap="md">
      {/* Summary badges */}
      <Group gap="sm">
        {updateCount > 0 && (
          <Badge variant="light" color="green" size="lg">
            {updateCount} to update
          </Badge>
        )}
        {skipCount > 0 && (
          <Badge variant="light" color="gray" size="lg">
            {skipCount} already set
          </Badge>
        )}
        {errorCount > 0 && (
          <Badge variant="light" color="red" size="lg">
            {errorCount} {errorCount === 1 ? 'warning' : 'warnings'}
          </Badge>
        )}
      </Group>

      <Divider />

      <AssetRows items={assetItems} />
      <ParameterRows items={parameterItems} />
      <PriceBreakRows items={priceBreakItems} />
    </Stack>
  );
}

/** Compact inline preview for bulk result cards. */
function CompactStructuredPreview({ result }: { result: EnrichResult }) {
  const diff = result.diff;

  if (!hasAnyContent(result)) {
    return <Text size="xs" c="dimmed">No changes</Text>;
  }

  const totalUpdates = result.updated.length;
  const totalErrors = result.errors.length;

  return (
    <Stack gap={4}>
      <Group gap="xs">
        {totalUpdates > 0 && (
          <Badge size="xs" variant="light" color="green">{totalUpdates} updates</Badge>
        )}
        {result.skipped.length > 0 && (
          <Badge size="xs" variant="light" color="gray">{result.skipped.length} skipped</Badge>
        )}
        {totalErrors > 0 && (
          <Badge size="xs" variant="light" color="red">{totalErrors} errors</Badge>
        )}
      </Group>

      {diff ? (
        /* Richer compact details when diff payload is present */
        <>
          {diff.image?.incoming && (
            <Text size="xs" c="green.7">
              Image: {diff.image.current ?? 'none'} → {diff.image.incoming.length > 40 ? `${diff.image.incoming.slice(0, 37)}...` : diff.image.incoming}
            </Text>
          )}
          {diff.datasheet?.incoming && (
            <Text size="xs" c="green.7">
              Datasheet: {diff.datasheet.current ?? 'none'} → {diff.datasheet.incoming.length > 40 ? `${diff.datasheet.incoming.slice(0, 37)}...` : diff.datasheet.incoming}
            </Text>
          )}
          {diff.parameters.filter((p) => p.status !== 'skipped').length > 0 && (
            <Text size="xs" c="green.7">
              Params: {diff.parameters.filter((p) => p.status !== 'skipped').map((p) => `${p.name}: ${p.current ?? '-'} → ${p.incoming ?? '-'}`).join(', ')}
            </Text>
          )}
          {diff.price_breaks.filter((p) => p.status !== 'skipped').length > 0 && (
            <Text size="xs" c="green.7">
              Prices: {diff.price_breaks.filter((p) => p.status !== 'skipped').map((p) => `${p.quantity}× ${p.incoming_currency} ${p.incoming_price}`).join(', ')}
            </Text>
          )}
        </>
      ) : (
        /* Fallback: old key-based parsing */
        (() => {
          const sections = parseResultKeys(result);
          return (
            <>
              {sections.assets.filter((i) => i.status === 'update').length > 0 && (
                <Text size="xs" c="green.7">
                  Assets: {sections.assets.filter((i) => i.status === 'update').map((i) => i.label).join(', ')}
                </Text>
              )}
              {sections.parameters.filter((i) => i.status === 'update').length > 0 && (
                <Text size="xs" c="green.7">
                  Params: {sections.parameters.filter((i) => i.status === 'update').map((i) => i.label).join(', ')}
                </Text>
              )}
              {sections.priceBreaks.filter((i) => i.status === 'update').length > 0 && (
                <Text size="xs" c="green.7">
                  Prices: {sections.priceBreaks.filter((i) => i.status === 'update').map((i) => i.label).join(', ')}
                </Text>
              )}
            </>
          );
        })()
      )}
    </Stack>
  );
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

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
        size="xl"
      >
        {previewLoading && (
          <Group><Loader size="sm" /><Text>Loading preview...</Text></Group>
        )}
        {previewResult && !previewLoading && (
          <Stack gap="md">
            <StructuredPreview result={previewResult} />
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
                    <CompactStructuredPreview result={result} />
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
