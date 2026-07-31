"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, GitBranch, Shield, Zap, FileCode, ArrowRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/input";
import { api, type Repository } from "@/lib/api";
import { scoreColor } from "@/lib/utils";

export default function DashboardPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listRepositories()
      .then((data) => setRepos(data.repositories))
      .catch(() => setRepos([]))
      .finally(() => setLoading(false));
  }, []);

  const readyRepos = repos.filter((r) => r.status === "ready");
  const avgScore =
    readyRepos.length > 0
      ? Math.round(readyRepos.reduce((s, r) => s + (r.health_score || 0), 0) / readyRepos.length)
      : null;

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground mt-1">
            Multi-agent code review & repository intelligence
          </p>
        </div>
        <Link href="/upload">
          <Button>
            <GitBranch className="h-4 w-4" />
            Add Repository
          </Button>
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard icon={FileCode} label="Repositories" value={repos.length.toString()} />
        <StatCard icon={Activity} label="Ready" value={readyRepos.length.toString()} />
        <StatCard
          icon={Shield}
          label="Avg Health Score"
          value={avgScore !== null ? `${avgScore}/100` : "—"}
          valueClass={avgScore !== null ? scoreColor(avgScore) : undefined}
        />
        <StatCard icon={Zap} label="Agents" value="9" subtitle="Specialized reviewers" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent Repositories</CardTitle>
          <CardDescription>Indexed repositories ready for AI-powered review</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : repos.length === 0 ? (
            <div className="text-center py-12">
              <FileCode className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <p className="text-muted-foreground mb-4">No repositories yet</p>
              <Link href="/upload">
                <Button variant="outline">Upload your first repository</Button>
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {repos.map((repo) => (
                <div
                  key={repo.id}
                  className="flex items-center justify-between p-4 rounded-lg border border-border hover:bg-secondary/50 transition-colors"
                >
                  <div>
                    <p className="font-medium">{repo.full_name}</p>
                    <p className="text-sm text-muted-foreground">
                      {repo.file_count} files · {repo.chunk_count} chunks
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge className={repo.status === "ready" ? "bg-green-400/10 text-green-400" : "bg-yellow-400/10 text-yellow-400"}>
                      {repo.status}
                    </Badge>
                    {repo.health_score && (
                      <span className={`font-bold ${scoreColor(repo.health_score)}`}>
                        {repo.health_score}
                      </span>
                    )}
                    <Link href={`/history?repo=${repo.id}`}>
                      <Button variant="ghost" size="sm">
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  subtitle,
  valueClass,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  subtitle?: string;
  valueClass?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className={`text-2xl font-bold ${valueClass || ""}`}>{value}</p>
            {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
