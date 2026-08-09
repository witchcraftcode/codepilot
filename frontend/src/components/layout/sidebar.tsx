"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Upload,
  MessageSquare,
  Shield,
  Layers,
  TestTube,
  FileText,
  History,
  Settings,
  BarChart3,
  Code2,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/upload", label: "Upload Repo", icon: Upload },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/security", label: "Security", icon: Shield },
  { href: "/architecture", label: "Architecture", icon: Layers },
  { href: "/testing", label: "Testing", icon: TestTube },
  { href: "/documentation", label: "Documentation", icon: FileText },
  { href: "/history", label: "History", icon: History },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-border bg-card flex flex-col">
      <div className="p-6 border-b border-border">
        <Link href="/" className="flex items-center gap-2">
          <Code2 className="h-7 w-7 text-primary" />
          <div>
            <h1 className="font-bold text-lg">CodePilot AI</h1>
            <p className="text-xs text-muted-foreground">Multi-Agent Review</p>
          </div>
        </Link>
      </div>
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
              pathname === href
                ? "bg-primary/10 text-primary font-medium"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
