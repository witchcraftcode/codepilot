"use client";

import { FileText } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function DocumentationPage() {
  return (
    <div className="p-8 space-y-6">
      <h1 className="text-3xl font-bold flex items-center gap-2">
        <FileText className="h-8 w-8 text-primary" /> Documentation
      </h1>
      <Card>
        <CardHeader>
          <CardTitle>Auto Documentation</CardTitle>
          <CardDescription>
            Generate README improvements, API docs, and function explanations
            using the Documentation Agent and /documentation API.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          One-click documentation generation for readme, api, or function-level targets.
        </CardContent>
      </Card>
    </div>
  );
}
