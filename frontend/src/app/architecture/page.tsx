"use client";

import { Layers } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function ArchitecturePage() {
  return (
    <div className="p-8 space-y-6">
      <h1 className="text-3xl font-bold flex items-center gap-2">
        <Layers className="h-8 w-8 text-primary" /> Architecture Review
      </h1>
      <Card>
        <CardHeader>
          <CardTitle>SOLID & Layering Analysis</CardTitle>
          <CardDescription>
            Run a full or architecture-focused review from the Dashboard or Upload page.
            The Architecture Agent evaluates separation of concerns, modularity, and design patterns.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="p-6 rounded-lg bg-secondary/50 font-mono text-sm">
            <pre>{`Repository → Folder → File → Class → Function → Method

Agents: Planner → Architecture → Security → Performance
        → Testing → Documentation → Style → Dependencies → Summary`}</pre>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
