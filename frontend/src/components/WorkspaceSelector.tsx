import { useState } from "react";
import { ChevronDown, Plus, Loader2, Pencil, Trash2, Check } from "lucide-react";
import type { Workspace } from "../types";

interface WorkspaceSelectorProps {
  workspaces: Workspace[];
  activeId: string;
  onSelect: (id: string) => void;
  onCreate: (name: string, domain: string, description: string, autoDiscover: boolean) => Promise<void>;
  onUpdate: (id: string, name: string, domain: string, description: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function WorkspaceSelector({
  workspaces,
  activeId,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
}: WorkspaceSelectorProps) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [description, setDescription] = useState("");
  const [autoDiscover, setAutoDiscover] = useState(false);

  // Edit state: which workspace id is being edited
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDomain, setEditDomain] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editSaving, setEditSaving] = useState(false);

  // Delete confirm state
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteWorking, setDeleteWorking] = useState(false);

  const active = workspaces.find((w) => w.id === activeId);

  function reset() {
    setName("");
    setDomain("");
    setDescription("");
    setAutoDiscover(false);
    setCreating(false);
  }

  function startEdit(w: Workspace, e: React.MouseEvent) {
    e.stopPropagation();
    setEditingId(w.id);
    setEditName(w.name);
    setEditDomain(w.domain);
    setEditDescription(w.description ?? "");
    setDeletingId(null);
  }

  function cancelEdit(e: React.MouseEvent) {
    e.stopPropagation();
    setEditingId(null);
  }

  async function commitEdit(id: string, e: React.FormEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!editName.trim() || !editDomain.trim()) return;
    setEditSaving(true);
    try {
      await onUpdate(id, editName.trim(), editDomain.trim(), editDescription.trim());
      setEditingId(null);
    } finally {
      setEditSaving(false);
    }
  }

  function startDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setDeletingId(id);
    setEditingId(null);
  }

  function cancelDelete(e: React.MouseEvent) {
    e.stopPropagation();
    setDeletingId(null);
  }

  async function confirmDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setDeleteWorking(true);
    try {
      await onDelete(id);
      setDeletingId(null);
      if (workspaces.length <= 1) setOpen(false);
    } finally {
      setDeleteWorking(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !domain.trim()) return;
    setSaving(true);
    try {
      await onCreate(name.trim(), domain.trim(), description.trim(), autoDiscover && !!description.trim());
      reset();
      setOpen(false);
    } finally {
      setSaving(false);
    }
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
          {workspaces.map((w) => {
            if (editingId === w.id) {
              return (
                <form
                  key={w.id}
                  onSubmit={(e) => commitEdit(w.id, e)}
                  onClick={(e) => e.stopPropagation()}
                  className="flex flex-col gap-1.5 rounded-md bg-zinc-800/50 p-2 mb-0.5"
                >
                  <input
                    autoFocus
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Workspace name"
                    className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500"
                  />
                  <input
                    value={editDomain}
                    onChange={(e) => setEditDomain(e.target.value)}
                    placeholder="Domain label"
                    className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500"
                  />
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    placeholder="Description (optional)"
                    rows={2}
                    className="resize-none rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500 leading-relaxed"
                  />
                  <div className="flex gap-1.5">
                    <button
                      type="submit"
                      disabled={editSaving || !editName.trim() || !editDomain.trim()}
                      className="flex flex-1 items-center justify-center gap-1 rounded bg-zinc-100 py-1 text-[12px] font-medium text-zinc-900 hover:bg-white disabled:opacity-40"
                    >
                      {editSaving ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                      {editSaving ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="rounded border border-zinc-700 px-2.5 py-1 text-[12px] text-zinc-500 hover:text-zinc-300"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              );
            }

            if (deletingId === w.id) {
              return (
                <div
                  key={w.id}
                  onClick={(e) => e.stopPropagation()}
                  className="flex flex-col gap-1.5 rounded-md bg-rose-950/30 border border-rose-900/40 p-2 mb-0.5"
                >
                  <p className="text-[11.5px] text-zinc-300">
                    Delete <span className="font-medium text-zinc-100">"{w.name}"</span>? This removes all its sources and reports.
                  </p>
                  <div className="flex gap-1.5">
                    <button
                      onClick={(e) => confirmDelete(w.id, e)}
                      disabled={deleteWorking}
                      className="flex flex-1 items-center justify-center gap-1 rounded bg-rose-700 py-1 text-[12px] font-medium text-white hover:bg-rose-600 disabled:opacity-40"
                    >
                      {deleteWorking ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                      {deleteWorking ? "Deleting…" : "Delete"}
                    </button>
                    <button
                      onClick={cancelDelete}
                      className="rounded border border-zinc-700 px-2.5 py-1 text-[12px] text-zinc-500 hover:text-zinc-300"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              );
            }

            return (
              <div key={w.id} className="group relative flex items-center rounded-md transition-colors">
                <button
                  onClick={() => { onSelect(w.id); setOpen(false); setEditingId(null); setDeletingId(null); }}
                  className={`flex-1 min-w-0 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
                    w.id === activeId ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-800/60"
                  }`}
                >
                  <span className="block truncate pr-12">{w.name}</span>
                </button>
                <div className="absolute right-1 hidden gap-0.5 group-hover:flex">
                  <button
                    onClick={(e) => startEdit(w, e)}
                    title="Rename workspace"
                    className="rounded p-1 text-zinc-500 hover:bg-zinc-700 hover:text-zinc-200 transition-colors"
                  >
                    <Pencil size={11} />
                  </button>
                  <button
                    onClick={(e) => startDelete(w.id, e)}
                    title="Delete workspace"
                    className="rounded p-1 text-zinc-500 hover:bg-rose-900/50 hover:text-rose-400 transition-colors"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            );
          })}

          <div className="mt-1 border-t border-zinc-800 pt-1">
            {creating ? (
              <form onSubmit={handleCreate} className="flex flex-col gap-2 p-1.5">
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Workspace name"
                  className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500"
                />
                <input
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="Short label, e.g. climate policy"
                  className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500"
                />
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Optional: describe the research area in 1–2 sentences. Used to auto-discover relevant sources."
                  rows={3}
                  className="resize-none rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-zinc-500 leading-relaxed"
                />
                {description.trim() && (
                  <label className="flex cursor-pointer items-center gap-2 px-0.5 text-[11.5px] text-zinc-400 hover:text-zinc-200">
                    <input
                      type="checkbox"
                      checked={autoDiscover}
                      onChange={(e) => setAutoDiscover(e.target.checked)}
                      className="h-3 w-3 rounded accent-zinc-300"
                    />
                    Auto-discover sources after creation
                  </label>
                )}
                <div className="flex gap-1.5">
                  <button
                    type="submit"
                    disabled={saving || !name.trim() || !domain.trim()}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-zinc-100 py-1.5 text-[12px] font-medium text-zinc-900 hover:bg-white disabled:opacity-40"
                  >
                    {saving ? <Loader2 size={12} className="animate-spin" /> : null}
                    {saving ? "Creating…" : "Create"}
                  </button>
                  <button
                    type="button"
                    onClick={reset}
                    className="rounded-md border border-zinc-700 px-3 py-1.5 text-[12px] text-zinc-500 hover:text-zinc-300"
                  >
                    Cancel
                  </button>
                </div>
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
