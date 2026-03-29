import type { InvenTreePluginContext } from '@inventreedb/ui';
import { Alert, Code, List, Stack, Text, Title } from '@mantine/core';

function SettingsPanel({ context }: { context: InvenTreePluginContext }) {
  return (
    <Stack gap="md">
      <Title order={4}>Supplier Part Import</Title>
      <Text c="dimmed" size="sm">
        Combined provider plugin for supplier search, import, single-part enrich, and bulk enrich.
      </Text>

      <Alert color="blue" title="Recommended settings">
        Configure one supplier company per provider, then enable only the providers you actually use.
      </Alert>

      <Stack gap={4}>
        <Text fw={700}>What this plugin provides</Text>
        <List size="sm">
          <List.Item>One combined supplier import plugin</List.Item>
          <List.Item>One modern part-detail enrich panel</List.Item>
          <List.Item>A dedicated bulk enrich page</List.Item>
          <List.Item>Provider-specific settings for LCSC and Mouser</List.Item>
        </List>
      </Stack>

      <Text size="sm">
        Active model context: <Code>{String(context.model ?? 'unknown')}</Code>
      </Text>
    </Stack>
  );
}

export function renderPluginSettings(context: InvenTreePluginContext) {
  return <SettingsPanel context={context} />;
}
