"use client";

import { useEffect, useState } from "react";
import { Shield, AlertTriangle, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/input";
import { api, type Repository, type ReviewDetail } from "@/lib/api";
import { severityColor, scoreColor } from "@/lib/utils";

export default function SecurityPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.listRepositories().then((d) => {
      const ready = d.repositories.filter((r) => r.status === "ready");
      setRepos(ready);
      if (ready.length > 0) setSelectedRepo(ready[0].id);
    });
  }, []);

  async function runAudit() {
    if (!selectedRepo) return;
    setLoading(true);
    setReview(null);
    try {
      const r = await api.securityAudit(selectedRepo);
      const poll = setInterval(async () => {
        const detail = await api.getReview(r.id);
        if (detail.status === "completed" || detail.status === "failed") {
          clearInterval(poll);
          setReview(detail);
          setLoading(false);
        }
      }, 3000);
    } catch {
      setLoading(false);
    }
  }

  const securityResult = review?.agent_results?.find((a) => a.agent_name === "security");

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-2">
          <Shield className="h-8 w-8 text-primary" />
          Security Audit
        </h1>
        <p className="text-muted-foreground mt-1">
          OWASP analysis, secret detection, injection vulnerabilities
        </p>
      </div>

      <Card>
        <CardContent className="pt-6 flex gap-4 items-end">
          <div className="flex-1">
            <label className="text-sm font-medium mb-1.5 block">Repository</label>
            <select
              value={selectedRepo}
              onChange={(e) => setSelectedRepo(e.target.value)}
              className="w-full h-10 rounded-md border border-border bg-secondary px-3 text-sm"
            >
              {repos.map((r) => (
                <option key={r.id} value={r.id}>{r.full_name}</option>
              ))}
            </select>
          </div>
          <Button onClick={runAudit} disabled={loading || !selectedRepo}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Run Security Audit"}
          </Button>
        </CardContent>
      </Card>

      {securityResult && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Security Findings
              <span className={`text-2xl ${scoreColor(securityResult.score || 0)}`}>
                {securityResult.score}/100
              </span>
            </CardTitle>
            <CardDescription>{securityResult.summary}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {securityResult.findings.map((f) => (
              <div key={f.id} className="p-4 rounded-lg border border-border">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="h-4 w-4" />
                  <Badge className={severityColor(f.severity)}>{f.severity}</Badge>
                  <span className="font-medium">{f.title}</span>
                </div>
                <p className="text-sm text-muted-foreground">{f.description}</p>
                {f.file_path && (
                  <p className="text-xs text-primary mt-2">{f.file_path}</p>
                )}
                {f.suggestion && (
                  <p className="text-sm mt-2 p-2 rounded bg-secondary">{f.suggestion}</p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
