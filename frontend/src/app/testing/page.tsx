"use client";

import { TestTube } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function TestingPage() {
  return (
    <div className="p-8 space-y-6">
      <h1 className="text-3xl font-bold flex items-center gap-2">
        <TestTube className="h-8 w-8 text-primary" /> Testing Analysis
      </h1>
      <Card>
        <CardHeader>
          <CardTitle>Test Coverage & Generation</CardTitle>
          <CardDescription>
            The Testing Agent identifies untested files, evaluates test quality, and generates
            pytest/Jest/JUnit tests via the /tests API endpoint.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          Use POST /api/v1/tests with repository_id, file_path, and optional function_name.
        </CardContent>
      </Card>
    </div>
  );
}
