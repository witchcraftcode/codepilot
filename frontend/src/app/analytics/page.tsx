"use client";

import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, Radar } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type Repository, type ScoresResponse } from "@/lib/api";

export default function AnalyticsPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [scores, setScores] = useState<ScoresResponse | null>(null);
  const [selectedRepo, setSelectedRepo] = useState("");

  useEffect(() => {
    api.listRepositories().then((d) => {
      const ready = d.repositories.filter((r) => r.status === "ready");
      setRepos(ready);
      if (ready.length > 0) setSelectedRepo(ready[0].id);
    });
  }, []);

  useEffect(() => {
    if (selectedRepo) {
      api.getScores(selectedRepo).then(setScores).catch(() => setScores(null));
    }
  }, [selectedRepo]);

  const radarData = scores
    ? [
        { metric: "Security", score: scores.health_score.security },
        { metric: "Performance", score: scores.health_score.performance },
        { metric: "Architecture", score: scores.health_score.architecture },
        { metric: "Documentation", score: scores.health_score.documentation },
        { metric: "Testing", score: scores.health_score.testing },
        { metric: "Maintainability", score: scores.health_score.maintainability },
      ]
    : [];

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-3xl font-bold">Analytics</h1>
      <select
        value={selectedRepo}
        onChange={(e) => setSelectedRepo(e.target.value)}
        className="h-10 rounded-md border border-border bg-secondary px-3 text-sm"
      >
        {repos.map((r) => (
          <option key={r.id} value={r.id}>{r.full_name}</option>
        ))}
      </select>

      {scores && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader><CardTitle>Health Score Breakdown</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={radarData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="metric" stroke="#94a3b8" fontSize={12} />
                  <YAxis domain={[0, 100]} stroke="#94a3b8" />
                  <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155" }} />
                  <Bar dataKey="score" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Radar Overview</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#334155" />
                  <PolarAngleAxis dataKey="metric" stroke="#94a3b8" fontSize={12} />
                  <Radar dataKey="score" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.3} />
                </RadarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
