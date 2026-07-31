"use client";

import { Settings } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function SettingsPage() {
  return (
    <div className="p-8 space-y-6 max-w-2xl">
      <h1 className="text-3xl font-bold flex items-center gap-2">
        <Settings className="h-8 w-8" /> Settings
      </h1>
      <Card>
        <CardHeader>
          <CardTitle>LLM Provider</CardTitle>
          <CardDescription>Configure via backend environment variables</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>LLM_PROVIDER: openai | anthropic | gemini | deepseek | ollama</p>
          <p>EMBEDDING_PROVIDER: openai | bge | nomic | voyage</p>
          <p>LANGSMITH_TRACING: true (for observability)</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>GitHub OAuth</CardTitle>
          <CardDescription>Connect your GitHub account for private repo access</CardDescription>
        </CardHeader>
        <CardContent>
          <a
            href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/auth/github`}
            className="inline-flex items-center px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium"
          >
            Connect GitHub
          </a>
        </CardContent>
      </Card>
    </div>
  );
}
