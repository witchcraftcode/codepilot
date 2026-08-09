import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(ms: number | null): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function severityColor(severity: string): string {
  const map: Record<string, string> = {
    critical: "text-red-400 bg-red-400/10",
    high: "text-orange-400 bg-orange-400/10",
    medium: "text-yellow-400 bg-yellow-400/10",
    low: "text-blue-400 bg-blue-400/10",
    info: "text-muted-foreground bg-secondary",
  };
  return map[severity] || map.info;
}

export function scoreColor(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-yellow-400";
  return "text-red-400";
}
