import { useState } from "react";
import { ChevronDown, Plus } from "lucide-react";
import type { Workspace } from "../types";

interface WorkspaceSelectorProps {
  workspaces: Workspace[];
  activeId: string;
  onSelect: (id: string) => void;
  onCreate: (name: string, domain: string) => Promise<void>;
}

export function WorkspaceSelector({ workspaces, activeId, onSelect, onCreate }: WorkspaceSelectorProps) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");

  const active = workspaces.find((w) => w.id === activeId);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !domain.trim()) return;
    await onCreate(name.trim(), domain.trim());
    setName("");
    setDomain("");
    setCreating(false);
    setOpen(false);
  }

  return (
    <div className="relative px-3 pb-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-left transition-colors hover:border-zinc-700"
      >
        <div className="min-w-0">
          <p className="truncate text-[12.5px] font-medium text-zinc-200">
            {active?.name ?? "Select workspace"}
          </p>
          <p className="truncate text-[10.5px] text-zinc-500">{active?.domain}</p>
        </div>
        <ChevronDown size={14} className="flex-shrink-0 text-zinc-500" />
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full z-10 mt-1 rounded-lg border border-zinc-800 bg-zinc-900 p-1 shadow-xl">
          {workspaces.map((w) => (
            <button
              key={w.id}
              onClick={() => {
                onSelect(w.id);
                setOpen(false);
              }}
              className={`w-full rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
                w.id === activeId ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800/60"
              }`}
            >
              {w.name}
            </button>
          ))}

          <div className="mt-1 border-t border-zinc-800 pt-1">
            {creating ? (
              <form onSubmit={handleCreate} className="flex flex-col gap-1.5 p-1.5">
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Workspace name"
                  className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500"
                />
                <input
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="Domain, e.g. climate policy"
                  className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500"
                />
                <button
                  type="submit"
                  className="mt-0.5 rounded-md bg-zinc-100 py-1 text-[12px] font-medium text-zinc-900 hover:bg-white"
                >
                  Create
                </button>
              </form>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="flex w-full items-center gap-1.5 rounded-md px-2.5 py-1.5 text-left text-[12.5px] text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-300"
              >
                <Plus size={13} />
                New workspace
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
