export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function formatMs(value: number | null | undefined, digits = 0): string {
  if (value == null) {
    return '—';
  }
  return `${value.toFixed(digits)} ms`;
}

export function formatClockTime(
  value: number,
  options?: { includeMilliseconds?: boolean },
): string {
  const formatOptions = {
    hour: 'numeric' as const,
    minute: '2-digit' as const,
    second: '2-digit' as const,
    ...(options?.includeMilliseconds ? { fractionalSecondDigits: 3 as const } : {}),
  } satisfies Intl.DateTimeFormatOptions;
  return new Intl.DateTimeFormat(undefined, formatOptions).format(new Date(value));
}
