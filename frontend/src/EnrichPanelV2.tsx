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
  status: 'new' | 'skipped' | 'updated';
};

type DiffSupplierPartRow = {
  field: string;
  current: string | null;
  incoming: string | null;
  status: 'new' | 'skipped' | 'updated';
};

type DiffParameterRow = {
  name: string;
  units?: string;
  current: string | null;
  incoming: string | null;
  status: 'new' | 'skipped' | 'updated';
};

type DiffPriceBreakRow = {
  quantity: number;
  current_price?: number | null;
  current_currency?: string | null;
  incoming_price: number;
  incoming_currency: string;
  status: 'new' | 'skipped' | 'updated';
};

type DiffManufacturerPartRow = {
  field: string;
  current: string | number | null;
  incoming: string | number | null;
  status: 'new' | 'skipped' | 'updated';
};

type DiffPayload = {
  image: DiffFieldEntry | null;
  datasheet: DiffFieldEntry | null;
  price_breaks: DiffPriceBreakRow[];
  parameters: DiffParameterRow[];
  part_fields: DiffFieldEntry[];
  supplier_part: DiffSupplierPartRow[];
  manufacturer_part: DiffManufacturerPartRow[];
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

type RichPartFieldItem = ParsedItem & {
  currentValue: string | null;
  incomingValue: string | null;
};

type RichPriceBreakItem = ParsedItem & {
  currentPrice: number | null;
  currentCurrency: string | null;
  incomingPrice: number | null;
  incomingCurrency: string | null;
};

type RichSupplierPartItem = ParsedItem & {
  currentValue: string | null;
  incomingValue: string | null;
};

type ParsedSections = {
  assets: ParsedItem[];
  partFields: ParsedItem[];
  parameters: ParsedItem[];
  priceBreaks: ParsedItem[];
  supplierParts: ParsedItem[];
  manufacturerParts: ParsedItem[];
};

type SelectionProps = {
  selectable?: boolean;
  selectedKeys?: Set<string>;
  onToggleKey?: (key: string) => void;
  sectionUpdateKeys?: string[];
  onToggleAllInSection?: (keys: string[], allSelected: boolean) => void;
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

const SUPPLIER_PART_FIELD_LABELS: Record<string, string> = {
  description: 'Supplier description',
  link: 'Supplier link',
  available: 'Available quantity',
};

const PART_FIELD_LABELS: Record<string, string> = {
  description: 'Part description',
  link: 'Part link',
};

/** Resolve the authoritative status for a key from the EnrichResult lists. */
function authoritativeStatus(key: string, result: EnrichResult): ItemStatus {
  if (result.skipped.includes(key)) return 'skip';
  if (result.updated.includes(key)) return 'update';
  return 'skip';
}

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
  if (raw.startsWith('part:')) {
    const field = raw.slice('part:'.length);
    return { section: 'partFields', label: PART_FIELD_LABELS[field] ?? field };
  }
  if (raw.startsWith('supplier_part:')) {
    const field = raw.slice('supplier_part:'.length);
    return { section: 'supplierParts', label: SUPPLIER_PART_FIELD_LABELS[field] ?? field };
  }
  if (raw.startsWith('supplier_parameter:')) {
    const name = raw.slice('supplier_parameter:'.length);
    return { section: 'parameters', label: `Supplier: ${name}` };
  }
  if (raw.startsWith('manufacturer_part:')) {
    const field = raw.slice('manufacturer_part:'.length);
    return { section: 'manufacturerParts', label: `Manufacturer: ${field}` };
  }
  return { section: 'assets', label: raw };
}

function parseResultKeys(result: EnrichResult): ParsedSections {
  const sections: ParsedSections = {
    assets: [],
    partFields: [],
    parameters: [],
    priceBreaks: [],
    supplierParts: [],
    manufacturerParts: [],
  };

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

  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.assets.map((item) => ({ ...item, currentValue: null, incomingValue: null }));
  }
  const items: RichAssetItem[] = [];
  if (diff.image) {
    items.push({
      key: 'image',
      label: 'Part image',
      status: authoritativeStatus('image', result),
      currentValue: diff.image.current,
      incomingValue: diff.image.incoming,
    });
  }
  if (diff.datasheet) {
    items.push({
      key: 'datasheet_link',
      label: 'Datasheet link',
      status: authoritativeStatus('datasheet_link', result),
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
    status: authoritativeStatus(`parameter:${row.name}`, result),
    currentValue: row.current,
    incomingValue: row.incoming,
    units: row.units,
  }));
}

function buildPartFieldItems(result: EnrichResult): RichPartFieldItem[] {
  const diff = result.diff;
  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.partFields.map((item) => ({ ...item, currentValue: null, incomingValue: null }));
  }
  return diff.part_fields.map((row) => ({
    key: `part:${row.field}`,
    label: PART_FIELD_LABELS[row.field] ?? row.field,
    status: authoritativeStatus(`part:${row.field}`, result),
    currentValue: row.current,
    incomingValue: row.incoming,
  }));
}

function buildPriceBreakItems(result: EnrichResult): RichPriceBreakItem[] {
  const diff = result.diff;
  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.priceBreaks.map((item) => ({
      ...item,
      currentPrice: null,
      currentCurrency: null,
      incomingPrice: null,
      incomingCurrency: null,
    }));
  }
  return diff.price_breaks.map((row) => ({
    key: `price_break:${row.quantity}`,
    label: `Qty ${row.quantity}`,
    status: authoritativeStatus(`price_break:${row.quantity}`, result),
    currentPrice: row.current_price ?? null,
    currentCurrency: row.current_currency ?? null,
    incomingPrice: row.incoming_price,
    incomingCurrency: row.incoming_currency,
  }));
}

function buildSupplierPartItems(result: EnrichResult): RichSupplierPartItem[] {
  const diff = result.diff;
  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.supplierParts.map((item) => ({ ...item, currentValue: null, incomingValue: null }));
  }
  return diff.supplier_part.map((row) => ({
    key: `supplier_part:${row.field}`,
    label: SUPPLIER_PART_FIELD_LABELS[row.field] ?? row.field,
    status: authoritativeStatus(`supplier_part:${row.field}`, result),
    currentValue: row.current != null ? String(row.current) : null,
    incomingValue: row.incoming != null ? String(row.incoming) : null,
  }));
}

function buildManufacturerPartItems(result: EnrichResult): RichSupplierPartItem[] {
  const diff = result.diff;
  if (!diff) {
    const sections = parseResultKeys(result);
    return sections.manufacturerParts.map((item) => ({ ...item, currentValue: null, incomingValue: null }));
  }
  return diff.manufacturer_part.map((row) => ({
    key: `manufacturer_part:${row.field}`,
    label: row.field === 'manufacturer_name' ? 'Manufacturer' : 'MPN',
    status: authoritativeStatus(`manufacturer_part:${row.field}`, result),
    currentValue: row.current != null ? String(row.current) : null,
    incomingValue: row.incoming != null ? String(row.incoming) : null,
  }));
}

function hasAnyContent(result: EnrichResult): boolean {
  return result.updated.length > 0 || result.skipped.length > 0 || result.errors.length > 0;
}

function updateKeysFromItems(items: readonly ParsedItem[]): string[] {
  return items.filter((i) => i.status === 'update').map((i) => i.key);
}

type PreviewSections = {
  assetItems: RichAssetItem[];
  partFieldItems: RichPartFieldItem[];
  parameterItems: RichParameterItem[];
  priceBreakItems: RichPriceBreakItem[];
  supplierPartItems: RichSupplierPartItem[];
  manufacturerPartItems: RichSupplierPartItem[];
};

function buildPreviewSections(result: EnrichResult): PreviewSections {
  return {
    assetItems: buildAssetItems(result),
    partFieldItems: buildPartFieldItems(result),
    parameterItems: buildParameterItems(result),
    priceBreakItems: buildPriceBreakItems(result),
    supplierPartItems: buildSupplierPartItems(result),
    manufacturerPartItems: buildManufacturerPartItems(result),
  };
}

function countPreviewStatuses(sections: PreviewSections): { updateCount: number; skipCount: number } {
  const items = [
    ...sections.assetItems,
    ...sections.partFieldItems,
    ...sections.parameterItems,
    ...sections.priceBreakItems,
    ...sections.supplierPartItems,
    ...sections.manufacturerPartItems,
  ];

  return {
    updateCount: items.filter((item) => item.status === 'update').length,
    skipCount: items.filter((item) => item.status === 'skip').length,
  };
}

function getSelectableResultKeys(result: EnrichResult): Set<string> {
  const sections = buildPreviewSections(result);
  return new Set(
    [
      ...sections.assetItems,
      ...sections.partFieldItems,
      ...sections.parameterItems,
      ...sections.priceBreakItems,
      ...sections.supplierPartItems,
      ...sections.manufacturerPartItems,
    ]
      .filter((item) => item.status === 'update')
      .map((item) => item.key)
  );
}

function expandSelectedKeysForApply(result: EnrichResult, selectedKeys: Set<string>): string[] {
  const expanded = new Set(selectedKeys);

  for (const key of selectedKeys) {
    if (!key.startsWith('parameter:')) {
      continue;
    }

    const parameterName = key.slice('parameter:'.length);
    const supplierParameterKey = `supplier_parameter:${parameterName}`;
    if (result.updated.includes(supplierParameterKey)) {
      expanded.add(supplierParameterKey);
    }
  }

  return Array.from(expanded);
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

function SectionHeader({ label, count, selectable, sectionUpdateKeys, selectedKeys, onToggleAllInSection }: {
  label: string;
  count: number;
  selectable?: boolean;
  sectionUpdateKeys?: string[];
  selectedKeys?: Set<string>;
  onToggleAllInSection?: (keys: string[], allSelected: boolean) => void;
}) {
  const allSelected = sectionUpdateKeys != null && sectionUpdateKeys.length > 0 &&
    sectionUpdateKeys.every((k) => selectedKeys?.has(k));
  const someSelected = sectionUpdateKeys != null && sectionUpdateKeys.length > 0 &&
    !allSelected && sectionUpdateKeys.some((k) => selectedKeys?.has(k));

  return (
    <Group gap="xs">
      {selectable && sectionUpdateKeys != null && sectionUpdateKeys.length > 0 && (
        <Checkbox
          size="xs"
          checked={allSelected}
          indeterminate={someSelected}
          onChange={() => onToggleAllInSection?.(sectionUpdateKeys, allSelected)}
          aria-label={`Select all ${label.toLowerCase()}`}
        />
      )}
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

function AssetRows({ items, selectable, selectedKeys, onToggleKey, sectionUpdateKeys, onToggleAllInSection }: {
  items: RichAssetItem[];
} & SelectionProps) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  const effectiveUpdateKeys = sectionUpdateKeys ?? updateKeysFromItems(items);
  return (
    <Stack gap={4}>
      <SectionHeader label="Assets" count={items.length} selectable={selectable} sectionUpdateKeys={effectiveUpdateKeys} selectedKeys={selectedKeys} onToggleAllInSection={onToggleAllInSection} />
      <Paper withBorder radius="sm" p="xs">
        <Stack gap={6}>
          {items.map((item) => (
            <Group key={item.key} justify="space-between" wrap="nowrap">
              <Group gap="xs" wrap="nowrap">
                {selectable && item.status === 'update' && (
                  <Checkbox
                    checked={selectedKeys?.has(item.key) ?? false}
                    onChange={() => onToggleKey?.(item.key)}
                    size="xs"
                    aria-label={`Select ${item.label}`}
                  />
                )}
                <Text size="sm">{item.label}</Text>
              </Group>
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

function ParameterRows({ items, selectable, selectedKeys, onToggleKey, sectionUpdateKeys, onToggleAllInSection }: {
  items: RichParameterItem[];
} & SelectionProps) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  const effectiveUpdateKeys = sectionUpdateKeys ?? updateKeysFromItems(items);
  return (
    <Stack gap={4}>
      <SectionHeader label="Parameters" count={items.length} selectable={selectable} sectionUpdateKeys={effectiveUpdateKeys} selectedKeys={selectedKeys} onToggleAllInSection={onToggleAllInSection} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            {selectable && <Table.Th w={40} />}
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
              {selectable && (
                <Table.Td>
                  {item.status === 'update' && (
                    <Checkbox
                      checked={selectedKeys?.has(item.key) ?? false}
                      onChange={() => onToggleKey?.(item.key)}
                      size="xs"
                      aria-label={`Select ${item.label}`}
                    />
                  )}
                </Table.Td>
              )}
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

function PriceBreakRows({ items, selectable, selectedKeys, onToggleKey, sectionUpdateKeys, onToggleAllInSection }: {
  items: RichPriceBreakItem[];
} & SelectionProps) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.incomingPrice !== null || i.currentPrice !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  const effectiveUpdateKeys = sectionUpdateKeys ?? updateKeysFromItems(items);
  return (
    <Stack gap={4}>
      <SectionHeader label="Price Breaks" count={items.length} selectable={selectable} sectionUpdateKeys={effectiveUpdateKeys} selectedKeys={selectedKeys} onToggleAllInSection={onToggleAllInSection} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            {selectable && <Table.Th w={40} />}
            <Table.Th><Text size="xs" fw={600}>Quantity</Text></Table.Th>
            {hasRichData && <Table.Th><Text size="xs" fw={600}>Current Price</Text></Table.Th>}
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
              {selectable && (
                <Table.Td>
                  {item.status === 'update' && (
                    <Checkbox
                      checked={selectedKeys?.has(item.key) ?? false}
                      onChange={() => onToggleKey?.(item.key)}
                      size="xs"
                      aria-label={`Select ${item.label}`}
                    />
                  )}
                </Table.Td>
              )}
              <Table.Td><Text size="sm">{item.label}</Text></Table.Td>
              {hasRichData && (
                <Table.Td>
                  {item.currentPrice != null ? (
                    <Text size="sm" c="dimmed">
                      {item.currentCurrency ? `${item.currentCurrency} ` : ''}{item.currentPrice}
                    </Text>
                  ) : (
                    <Text size="xs" c="dimmed" fs="italic">-</Text>
                  )}
                </Table.Td>
              )}
              {hasRichData && (
                <Table.Td>
                  {item.incomingPrice != null ? (
                    <Text size="sm" c="green.8">
                      {item.incomingCurrency ? `${item.incomingCurrency} ` : ''}{item.incomingPrice}
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

function PartFieldRows({ items, selectable, selectedKeys, onToggleKey, sectionUpdateKeys, onToggleAllInSection }: {
  items: RichPartFieldItem[];
} & SelectionProps) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  const effectiveUpdateKeys = sectionUpdateKeys ?? updateKeysFromItems(items);
  return (
    <Stack gap={4}>
      <SectionHeader label="Part Fields" count={items.length} selectable={selectable} sectionUpdateKeys={effectiveUpdateKeys} selectedKeys={selectedKeys} onToggleAllInSection={onToggleAllInSection} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            {selectable && <Table.Th w={40} />}
            <Table.Th><Text size="xs" fw={600}>Field</Text></Table.Th>
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
              {selectable && (
                <Table.Td>
                  {item.status === 'update' && (
                    <Checkbox
                      checked={selectedKeys?.has(item.key) ?? false}
                      onChange={() => onToggleKey?.(item.key)}
                      size="xs"
                      aria-label={`Select ${item.label}`}
                    />
                  )}
                </Table.Td>
              )}
              <Table.Td><Text size="sm">{item.label}</Text></Table.Td>
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

function SupplierPartRows({ items, selectable, selectedKeys, onToggleKey, sectionUpdateKeys, onToggleAllInSection }: {
  items: RichSupplierPartItem[];
} & SelectionProps) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  const effectiveUpdateKeys = sectionUpdateKeys ?? updateKeysFromItems(items);
  return (
    <Stack gap={4}>
      <SectionHeader label="Supplier Part" count={items.length} selectable={selectable} sectionUpdateKeys={effectiveUpdateKeys} selectedKeys={selectedKeys} onToggleAllInSection={onToggleAllInSection} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            {selectable && <Table.Th w={40} />}
            <Table.Th><Text size="xs" fw={600}>Field</Text></Table.Th>
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
              {selectable && (
                <Table.Td>
                  {item.status === 'update' && (
                    <Checkbox
                      checked={selectedKeys?.has(item.key) ?? false}
                      onChange={() => onToggleKey?.(item.key)}
                      size="xs"
                      aria-label={`Select ${item.label}`}
                    />
                  )}
                </Table.Td>
              )}
              <Table.Td><Text size="sm">{item.label}</Text></Table.Td>
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

function ManufacturerPartRows({ items, selectable, selectedKeys, onToggleKey, sectionUpdateKeys, onToggleAllInSection }: {
  items: RichSupplierPartItem[];
} & SelectionProps) {
  if (items.length === 0) return null;
  const hasRichData = items.some((i) => i.currentValue !== null || i.incomingValue !== null);
  const updates = items.filter((i) => i.status === 'update');
  const skips = items.filter((i) => i.status === 'skip');
  const sorted = [...updates, ...skips];
  const effectiveUpdateKeys = sectionUpdateKeys ?? updateKeysFromItems(items);
  return (
    <Stack gap={4}>
      <SectionHeader label="Manufacturer Part" count={items.length} selectable={selectable} sectionUpdateKeys={effectiveUpdateKeys} selectedKeys={selectedKeys} onToggleAllInSection={onToggleAllInSection} />
      <Table withTableBorder withColumnBorders verticalSpacing={4} horizontalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            {selectable && <Table.Th w={40} />}
            <Table.Th><Text size="xs" fw={600}>Field</Text></Table.Th>
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
              {selectable && (
                <Table.Td>
                  {item.status === 'update' && (
                    <Checkbox
                      checked={selectedKeys?.has(item.key) ?? false}
                      onChange={() => onToggleKey?.(item.key)}
                      size="xs"
                      aria-label={`Select ${item.label}`}
                    />
                  )}
                </Table.Td>
              )}
              <Table.Td><Text size="sm">{item.label}</Text></Table.Td>
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

function StructuredPreview({ result }: { result: EnrichResult }) {
  const sections = useMemo(() => buildPreviewSections(result), [result]);

  if (!hasAnyContent(result)) {
    return (
      <Text size="sm" c="dimmed" ta="center" py="md">
        No changes detected from this provider.
      </Text>
    );
  }

  const { updateCount, skipCount } = countPreviewStatuses(sections);
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

      <AssetRows items={sections.assetItems} />
      <PartFieldRows items={sections.partFieldItems} />
      <SupplierPartRows items={sections.supplierPartItems} />
      <ManufacturerPartRows items={sections.manufacturerPartItems} />
      <ParameterRows items={sections.parameterItems} />
      <PriceBreakRows items={sections.priceBreakItems} />
    </Stack>
  );
}

/** Structured preview with per-key selection controls for bulk operations. */
function BulkStructuredPreview({
  result,
  selectedKeys,
  onToggleKey,
  onToggleAllInSection,
  onToggleAllForResult,
}: {
  result: EnrichResult;
  selectedKeys: Set<string>;
  onToggleKey: (key: string) => void;
  onToggleAllInSection?: (keys: string[], allSelected: boolean) => void;
  onToggleAllForResult?: (allSelected: boolean) => void;
}) {
  const sections = useMemo(() => buildPreviewSections(result), [result]);

  if (!hasAnyContent(result)) {
    return <Text size="sm" c="dimmed" ta="center" py="md">No changes detected from this provider.</Text>;
  }

  const { updateCount, skipCount } = countPreviewStatuses(sections);
  const errorCount = result.errors.length;

  const allUpdateKeys = getSelectableResultKeys(result);
  const allResultSelected = allUpdateKeys.size > 0 && Array.from(allUpdateKeys).every((k) => selectedKeys.has(k));
  const someResultSelected = !allResultSelected && Array.from(allUpdateKeys).some((k) => selectedKeys.has(k));

  const handleSectionToggle = (keys: string[], allSelected: boolean) => {
    onToggleAllInSection
      ? onToggleAllInSection(keys, allSelected)
      : keys.forEach((k) => {
          if (allSelected) onToggleKey(k);
          else if (!selectedKeys.has(k)) onToggleKey(k);
        });
  };

  return (
    <Stack gap="md">
      <Group gap="sm">
        {updateCount > 0 && (
          <Badge variant="light" color="green" size="lg">{updateCount} to update</Badge>
        )}
        {skipCount > 0 && (
          <Badge variant="light" color="gray" size="lg">{skipCount} already set</Badge>
        )}
        {errorCount > 0 && (
          <Badge variant="light" color="red" size="lg">
            {errorCount} {errorCount === 1 ? 'warning' : 'warnings'}
          </Badge>
        )}
        {onToggleAllForResult && allUpdateKeys.size > 0 && (
          <Checkbox
            size="xs"
            label="Select all"
            checked={allResultSelected}
            indeterminate={someResultSelected}
            onChange={() => onToggleAllForResult(allResultSelected)}
          />
        )}
      </Group>

      <Divider />

      <AssetRows items={sections.assetItems} selectable selectedKeys={selectedKeys} onToggleKey={onToggleKey} sectionUpdateKeys={updateKeysFromItems(sections.assetItems)} onToggleAllInSection={handleSectionToggle} />
      <PartFieldRows items={sections.partFieldItems} selectable selectedKeys={selectedKeys} onToggleKey={onToggleKey} sectionUpdateKeys={updateKeysFromItems(sections.partFieldItems)} onToggleAllInSection={handleSectionToggle} />
      <SupplierPartRows items={sections.supplierPartItems} selectable selectedKeys={selectedKeys} onToggleKey={onToggleKey} sectionUpdateKeys={updateKeysFromItems(sections.supplierPartItems)} onToggleAllInSection={handleSectionToggle} />
      <ManufacturerPartRows items={sections.manufacturerPartItems} selectable selectedKeys={selectedKeys} onToggleKey={onToggleKey} sectionUpdateKeys={updateKeysFromItems(sections.manufacturerPartItems)} onToggleAllInSection={handleSectionToggle} />
      <ParameterRows items={sections.parameterItems} selectable selectedKeys={selectedKeys} onToggleKey={onToggleKey} sectionUpdateKeys={updateKeysFromItems(sections.parameterItems)} onToggleAllInSection={handleSectionToggle} />
      <PriceBreakRows items={sections.priceBreakItems} selectable selectedKeys={selectedKeys} onToggleKey={onToggleKey} sectionUpdateKeys={updateKeysFromItems(sections.priceBreakItems)} onToggleAllInSection={handleSectionToggle} />
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
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());

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
      setSelectedKeys(getSelectableResultKeys(response.data));
    } catch (err) {
      setPreviewResult({
        provider_slug: provider.slug,
        provider_name: provider.name,
        part_id: partId,
        updated: [],
        skipped: [],
        errors: [String(err)],
      });
      setSelectedKeys(new Set());
    } finally {
      setPreviewLoading(false);
    }
  };

  const toggleKey = useCallback((key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const applyProvider = async () => {
    if (!previewResult) return;
    setApplyLoading(true);
    try {
      const expandedKeys = expandSelectedKeysForApply(previewResult, selectedKeys);
      const response = await context.api.post<EnrichResult>(
        pluginApi(pluginSlug, `part/${partId}/apply/${previewResult.provider_slug}/`),
        { selected_keys: expandedKeys }
      );
      setPreviewResult(response.data);
      setSelectedKeys(new Set());
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
        size="80vw"
      >
        {previewLoading && (
          <Group><Loader size="sm" /><Text>Loading preview...</Text></Group>
        )}
        {previewResult && !previewLoading && (
          <Stack gap="md">
            <BulkStructuredPreview
              result={previewResult}
              selectedKeys={selectedKeys}
              onToggleKey={toggleKey}
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setPreviewResult(null)} disabled={applyLoading}>
                Close
              </Button>
              <Button
                onClick={() => { void applyProvider(); }}
                loading={applyLoading}
                disabled={selectedKeys.size === 0}
              >
                Apply selected ({selectedKeys.size})
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
  const [bulkSelectedKeys, setBulkSelectedKeys] = useState<Record<string, Set<string>>>({});
  const [bulkError, setBulkError] = useState<string | null>(null);

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

  /* -- bulk key selection helper -- */
  const toggleBulkKey = useCallback((resultKey: string, key: string) => {
    setBulkSelectedKeys((prev) => {
      const next = { ...prev };
      const keys = new Set(next[resultKey] ?? new Set());
      if (keys.has(key)) keys.delete(key);
      else keys.add(key);
      next[resultKey] = keys;
      return next;
    });
  }, []);

  /* -- per-result-card select-all -- */
  const toggleAllForBulkResult = useCallback((resultKey: string, allSelected: boolean) => {
    setBulkSelectedKeys((prev) => {
      const next = { ...prev };
      if (allSelected) {
        next[resultKey] = new Set();
      } else {
        const result = bulkResult?.results.find(
          (r) => `${r.part_id}-${r.provider_slug}` === resultKey
        );
        next[resultKey] = result ? getSelectableResultKeys(result) : new Set();
      }
      return next;
    });
  }, [bulkResult]);

  /* -- per-section select-all (within a result card) -- */
  const toggleSectionKeys = useCallback((resultKey: string, keys: string[], allSelected: boolean) => {
    setBulkSelectedKeys((prev) => {
      const next = { ...prev };
      const current = new Set(next[resultKey] ?? new Set());
      if (allSelected) {
        keys.forEach((k) => current.delete(k));
      } else {
        keys.forEach((k) => current.add(k));
      }
      next[resultKey] = current;
      return next;
    });
  }, []);

  /* -- part identity lookup -- */
  const partsById = useMemo(() => {
    const map = new Map<number, CategoryPart>();
    for (const part of parts) map.set(part.pk, part);
    return map;
  }, [parts]);

  /* -- bulk operations -- */
  const canOperate = selectedPartIds.size > 0 && selectedProviderSlugs.length > 0;

  const runBulkPreview = useCallback(async () => {
    if (!canOperate) return;
    setBulkLoading(true);
    setBulkMode('preview');
    setBulkResult(null);
    setBulkError(null);
    try {
      const response = await context.api.post<BulkResponse>(
        pluginApi(pluginSlug, 'bulk/preview/'),
        { part_ids: Array.from(selectedPartIds), provider_slugs: selectedProviderSlugs },
      );
      setBulkResult(response.data);
      const init: Record<string, Set<string>> = {};
      for (const result of response.data.results) {
        const resultKey = `${result.part_id}-${result.provider_slug}`;
        init[resultKey] = getSelectableResultKeys(result);
      }
      setBulkSelectedKeys(init);
    } catch (err) {
      setBulkError(String(err));
      setBulkResult({
        results: [],
        summary: { requested_parts: selectedPartIds.size, provider_count: selectedProviderSlugs.length, operations: 0, failed: 1, succeeded: 0 },
      });
      setBulkSelectedKeys({});
    } finally {
      setBulkLoading(false);
    }
  }, [canOperate, context.api, pluginSlug, selectedPartIds, selectedProviderSlugs]);

  const totalSelectedKeys = useMemo(() => {
    let count = 0;
    for (const keys of Object.values(bulkSelectedKeys)) {
      count += keys.size;
    }
    return count;
  }, [bulkSelectedKeys]);

  const runBulkApply = useCallback(async () => {
    if (!bulkResult) return;

    const operations = bulkResult.results
      .map((result) => {
        const resultKey = `${result.part_id}-${result.provider_slug}`;
        const keys = bulkSelectedKeys[resultKey];
        return {
          part_id: result.part_id,
          provider_slug: result.provider_slug,
          selected_keys: keys ? expandSelectedKeysForApply(result, keys) : [],
        };
      })
      .filter((op) => op.selected_keys.length > 0);

    if (operations.length === 0) return;

    setBulkLoading(true);
    setBulkError(null);
    try {
      const response = await context.api.post<BulkResponse>(
        pluginApi(pluginSlug, 'bulk/apply/'),
        { operations },
      );
      setBulkResult(response.data);
      setBulkMode('apply');
      setBulkSelectedKeys({});
    } catch (err) {
      setBulkError(String(err));
      setBulkResult({
        results: [],
        summary: {
          requested_parts: operations.length,
          provider_count: new Set(operations.map((o) => o.provider_slug)).size,
          operations: operations.length,
          failed: operations.length,
          succeeded: 0,
        },
      });
    } finally {
      setBulkLoading(false);
    }
  }, [bulkResult, bulkSelectedKeys, context.api, pluginSlug]);

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
                  onClick={() => { void runBulkPreview(); }}
                >
                  Preview selected
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
        onClose={() => { if (!bulkLoading) { setBulkResult(null); setBulkSelectedKeys({}); setBulkError(null); } }}
        title={bulkMode === 'preview' ? 'Bulk Preview Results' : 'Bulk Apply Results'}
        size="90vw"
        fullScreen={false}
        yOffset={0}
        styles={{
          content: { maxHeight: '92vh', display: 'flex', flexDirection: 'column' },
          body: { flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 },
        }}
      >
        {bulkLoading && (
          <Group><Loader size="sm" /><Text>Processing...</Text></Group>
        )}
        {bulkResult && !bulkLoading && (
          <Stack gap="md" style={{ flex: 1, minHeight: 0 }}>
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
            <ScrollArea.Autosize mah="calc(92vh - 220px)" style={{ flex: 1 }}>
              <Stack gap="sm">
                {bulkResult.results.map((result) => {
                  const resultKey = `${result.part_id}-${result.provider_slug}`;
                  const selectedKeys = bulkSelectedKeys[resultKey] ?? new Set<string>();
                  const partInfo = partsById.get(result.part_id);
                  return (
                    <Card
                      key={resultKey}
                      withBorder
                      radius="sm"
                      padding="md"
                    >
                      <Group gap="xs" mb={4}>
                        <Text size="sm" fw={600}>
                          {partInfo ? partInfo.name : `Part #${result.part_id}`}
                        </Text>
                        {partInfo?.IPN && (
                          <Text size="xs" c="dimmed">({partInfo.IPN})</Text>
                        )}
                        <Text size="xs" c="dimmed">#{result.part_id}</Text>
                        <Badge size="sm" variant="dot">{result.provider_name}</Badge>
                        {partInfo?.description && (
                          <Tooltip label={partInfo.description} openDelay={400} maw={400}>
                            <Text size="xs" c="dimmed" truncate="end" maw={260} fs="italic">
                              {partInfo.description}
                            </Text>
                          </Tooltip>
                        )}
                      </Group>
                      {bulkMode === 'preview' ? (
                        <BulkStructuredPreview
                          result={result}
                          selectedKeys={selectedKeys}
                          onToggleKey={(key) => toggleBulkKey(resultKey, key)}
                          onToggleAllInSection={(keys, allSel) => toggleSectionKeys(resultKey, keys, allSel)}
                          onToggleAllForResult={(allSel) => toggleAllForBulkResult(resultKey, allSel)}
                        />
                      ) : (
                        <StructuredPreview result={result} />
                      )}
                    </Card>
                  );
                })}

                {bulkResult.results.length === 0 && (
                  bulkError ? (
                    <Alert color="red" title="Bulk operation failed">{bulkError}</Alert>
                  ) : (
                    <Text c="dimmed" size="sm" ta="center">No results returned.</Text>
                  )
                )}
              </Stack>
            </ScrollArea.Autosize>

            <Group justify="flex-end">
              <Button variant="default" onClick={() => { setBulkResult(null); setBulkSelectedKeys({}); setBulkError(null); }}>
                Close
              </Button>
              {bulkMode === 'preview' && (
                <Button
                  onClick={() => { void runBulkApply(); }}
                  disabled={totalSelectedKeys === 0}
                >
                  Apply selected ({totalSelectedKeys})
                </Button>
              )}
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
