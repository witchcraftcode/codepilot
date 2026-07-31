"use client";

import { useEffect, useState } from "react";
import { Send, Bot, User } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type Repository, type ChatResponse } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: ChatResponse["sources"];
}

export default function ChatPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.listRepositories().then((d) => {
      const ready = d.repositories.filter((r) => r.status === "ready");
      setRepos(ready);
      if (ready.length > 0) setSelectedRepo(ready[0].id);
    });
  }, []);

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || !selectedRepo) return;

    const userMsg = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: userMsg }]);
    setLoading(true);

    try {
      const res = await api.chat(selectedRepo, userMsg, conversationId);
      setConversationId(res.conversation_id);
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.message, sources: res.sources },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Sorry, I couldn't process that request." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 h-full flex flex-col max-w-4xl mx-auto">
      <Card className="flex-1 flex flex-col">
        <CardHeader className="border-b border-border">
          <CardTitle>Chat with Repository</CardTitle>
          <select
            value={selectedRepo}
            onChange={(e) => {
              setSelectedRepo(e.target.value);
              setMessages([]);
              setConversationId(undefined);
            }}
            className="mt-2 h-10 rounded-md border border-border bg-secondary px-3 text-sm"
          >
            {repos.map((r) => (
              <option key={r.id} value={r.id}>{r.full_name}</option>
            ))}
          </select>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col p-0">
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            {messages.length === 0 && (
              <p className="text-muted-foreground text-center py-12">
                Ask anything about the codebase — &quot;Where is authentication implemented?&quot;
              </p>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-3 ${msg.role === "user" ? "justify-end" : ""}`}>
                {msg.role === "assistant" && <Bot className="h-6 w-6 text-primary shrink-0" />}
                <div
                  className={`max-w-[80%] rounded-lg p-4 ${
                    msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-secondary"
                  }`}
                >
                  <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-border/50">
                      <p className="text-xs text-muted-foreground mb-1">Sources:</p>
                      {msg.sources.map((s, j) => (
                        <p key={j} className="text-xs text-primary">
                          {s.file_path} ({s.chunk_type})
                        </p>
                      ))}
                    </div>
                  )}
                </div>
                {msg.role === "user" && <User className="h-6 w-6 shrink-0" />}
              </div>
            ))}
          </div>
          <form onSubmit={sendMessage} className="p-4 border-t border-border flex gap-2">
            <Input
              placeholder="Ask about the codebase..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading || !selectedRepo}
            />
            <Button type="submit" disabled={loading || !selectedRepo}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
