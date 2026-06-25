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

const FIELD =
  "rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 text-[12px] text-paper outline-none placeholder:text-faint focus:border-brass/50";

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
        className="flex w-full items-center justify-between rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2 text-left transition-colors hover:border-ink-600"
      >
        <div className="min-w-0">
          <p className="truncate text-[12.5px] font-medium text-paper-dim">
            {active?.name ?? "Pick a workspace"}
          </p>
          <p className="truncate text-[10.5px] text-faint">{active?.domain}</p>
        </div>
        <ChevronDown size={14} className="flex-shrink-0 text-muted" />
      </button>

      {open && (
        <div className="absolute left-3 right-3 top-full z-10 mt-1 rounded-lg border border-ink-700 bg-ink-800 p-1 shadow-2xl shadow-black/40">
          {workspaces.map((w) => {
            if (editingId === w.id) {
              return (
                <form
                  key={w.id}
                  onSubmit={(e) => commitEdit(w.id, e)}
                  onClick={(e) => e.stopPropagation()}
                  className="flex flex-col gap-1.5 rounded-md bg-ink-750 p-2 mb-0.5"
                >
                  <input
                    autoFocus
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder="Workspace name"
                    className={FIELD}
                  />
                  <input
                    value={editDomain}
                    onChange={(e) => setEditDomain(e.target.value)}
                    placeholder="Domain label"
                    className={FIELD}
                  />
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    placeholder="Description (optional)"
                    rows={2}
                    className={`${FIELD} resize-none leading-relaxed`}
                  />
                  <div className="flex gap-1.5">
                    <button
                      type="submit"
                      disabled={editSaving || !editName.trim() || !editDomain.trim()}
                      className="flex flex-1 items-center justify-center gap-1 rounded bg-brass py-1 text-[12px] font-medium text-ink-900 hover:bg-brass-bright disabled:opacity-40"
                    >
                      {editSaving ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                      {editSaving ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="rounded border border-ink-600 px-2.5 py-1 text-[12px] text-muted hover:text-paper-dim"
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
                  className="flex flex-col gap-1.5 rounded-md bg-flag-dim border border-flag/30 p-2 mb-0.5"
                >
                  <p className="text-[11.5px] text-paper-dim">
                    Delete <span className="font-medium text-paper">"{w.name}"</span>? Its sources and reports go with it.
                  </p>
                  <div className="flex gap-1.5">
                    <button
                      onClick={(e) => confirmDelete(w.id, e)}
                      disabled={deleteWorking}
                      className="flex flex-1 items-center justify-center gap-1 rounded bg-flag py-1 text-[12px] font-medium text-ink-950 hover:brightness-110 disabled:opacity-40"
                    >
                      {deleteWorking ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                      {deleteWorking ? "Deleting…" : "Delete"}
                    </button>
                    <button
                      onClick={cancelDelete}
                      className="rounded border border-ink-600 px-2.5 py-1 text-[12px] text-muted hover:text-paper-dim"
                    >
                      Keep
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
                    w.id === activeId ? "bg-ink-700 text-paper" : "text-muted hover:bg-ink-750"
                  }`}
                >
                  <span className="block truncate pr-12">{w.name}</span>
                </button>
                <div className="absolute right-1 hidden gap-0.5 group-hover:flex">
                  <button
                    onClick={(e) => startEdit(w, e)}
                    title="Rename workspace"
                    className="rounded p-1 text-muted hover:bg-ink-650 hover:text-paper-dim transition-colors"
                  >
                    <Pencil size={11} />
                  </button>
                  <button
                    onClick={(e) => startDelete(w.id, e)}
                    title="Delete workspace"
                    className="rounded p-1 text-muted hover:bg-flag/15 hover:text-flag transition-colors"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            );
          })}

          <div className="mt-1 border-t border-ink-700 pt-1">
            {creating ? (
              <form onSubmit={handleCreate} className="flex flex-col gap-2 p-1.5">
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Workspace name"
                  className={FIELD}
                />
                <input
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="Short label, e.g. climate policy"
                  className={FIELD}
                />
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Optional: a sentence or two on the research area. Used to suggest sources."
                  rows={3}
                  className={`${FIELD} resize-none leading-relaxed`}
                />
                {description.trim() && (
                  <label className="flex cursor-pointer items-center gap-2 px-0.5 text-[11.5px] text-muted hover:text-paper-dim">
                    <input
                      type="checkbox"
                      checked={autoDiscover}
                      onChange={(e) => setAutoDiscover(e.target.checked)}
                      className="h-3 w-3 rounded accent-brass"
                    />
                    Suggest sources once it's created
                  </label>
                )}
                <div className="flex gap-1.5">
                  <button
                    type="submit"
                    disabled={saving || !name.trim() || !domain.trim()}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-brass py-1.5 text-[12px] font-medium text-ink-900 hover:bg-brass-bright disabled:opacity-40"
                  >
                    {saving ? <Loader2 size={12} className="animate-spin" /> : null}
                    {saving ? "Creating…" : "Create"}
                  </button>
                  <button
                    type="button"
                    onClick={reset}
                    className="rounded-md border border-ink-600 px-3 py-1.5 text-[12px] text-muted hover:text-paper-dim"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="flex w-full items-center gap-1.5 rounded-md px-2.5 py-1.5 text-left text-[12.5px] text-muted hover:bg-ink-750 hover:text-paper-dim"
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
