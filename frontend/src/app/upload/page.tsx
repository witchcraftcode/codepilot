"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GitBranch, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const repo = await api.createRepository(url, branch || undefined);
      router.push(`/?indexed=${repo.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to index repository");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-2xl mx-auto">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="h-5 w-5" />
            Upload Repository
          </CardTitle>
          <CardDescription>
            Paste a GitHub URL to clone, parse, chunk, and embed your codebase for AI review
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">GitHub URL</label>
              <Input
                placeholder="https://github.com/owner/repository"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">Branch (optional)</label>
              <Input
                placeholder="main"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-red-400">{error}</p>}
            <Button type="submit" disabled={loading} className="w-full">
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Indexing repository...
                </>
              ) : (
                "Index & Analyze"
              )}
            </Button>
          </form>

          <div className="mt-8 p-4 rounded-lg bg-secondary/50 text-sm text-muted-foreground space-y-2">
            <p className="font-medium text-foreground">What happens next:</p>
            <ol className="list-decimal list-inside space-y-1">
              <li>Clone repository via Git</li>
              <li>Parse structure, languages, dependencies</li>
              <li>AST-based hierarchical chunking</li>
              <li>Generate embeddings → Qdrant vector store</li>
              <li>Ready for multi-agent review</li>
            </ol>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
