"use client";

import { useEffect, useState } from "react";
import { History, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/input";
import { api, type Review } from "@/lib/api";
import { formatDuration, scoreColor } from "@/lib/utils";

export default function HistoryPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getHistory().then((d) => setReviews(d.reviews)).finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-3xl font-bold flex items-center gap-2">
        <History className="h-8 w-8" /> Review History
      </h1>
      <Card>
        <CardHeader><CardTitle>Past Reviews</CardTitle></CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : reviews.length === 0 ? (
            <p className="text-muted-foreground text-center py-8">No reviews yet</p>
          ) : (
            <div className="space-y-3">
              {reviews.map((r) => (
                <div key={r.id} className="flex items-center justify-between p-4 rounded-lg border border-border">
                  <div>
                    <p className="font-medium capitalize">{r.review_type} Review</p>
                    <p className="text-sm text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(r.created_at).toLocaleString()} · {formatDuration(r.duration_ms)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge className={r.status === "completed" ? "bg-green-400/10 text-green-400" : "bg-yellow-400/10 text-yellow-400"}>
                      {r.status}
                    </Badge>
                    {r.overall_score && (
                      <span className={`font-bold ${scoreColor(r.overall_score)}`}>{r.overall_score}</span>
                    )}
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
