import { useState, useEffect, useRef, useLayoutEffect } from 'preact/hooks';
import { fetchLibrary, fetchLibraryItem, saveLibraryItem } from '@/api/client';
import type { LibraryItem } from '@/api/client';
import { xmlToHr } from '@/converter/xml-to-hr';

interface LibraryPanelProps {
  onInsert: (content: string) => void;
  onStatus: (msg: string) => void;
  getEditorContent: () => string;
  getEditorSelection: () => string | null;
}

interface SaveDialog {
  everything: string;
  selection: string | null;
}

function formatSize(bytes: number): string {
  return bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${bytes} B`;
}

interface NewSectionDialogProps {
  categories: string[];
  error: string;
  onError: (msg: string) => void;
  onCreate: (name: string) => void;
  onClose: () => void;
}

function NewSectionDialog({ categories, error, onError, onCreate, onClose }: NewSectionDialogProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useLayoutEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleConfirm = () => {
    const trimmed = (inputRef.current?.value ?? '').trim();
    if (!trimmed) return;
    if (categories.some(c => c.toLowerCase() === trimmed.toLowerCase())) {
      onError(`"${trimmed}" already exists`);
      return;
    }
    onCreate(trimmed);
  };

  return (
    <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div class="bg-neutral-800 rounded-lg shadow-xl w-72 max-w-[90vw]">
        <div class="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
          <h2 class="text-sm font-semibold text-neutral-200">New Section</h2>
          <button
            onClick={onClose}
            class="text-neutral-400 hover:text-neutral-200 text-lg leading-none"
          >
            &times;
          </button>
        </div>
        <div class="px-4 py-3">
          <input
            ref={inputRef}
            type="text"
            onInput={() => onError('')}
            onKeyDown={e => {
              if (e.key === 'Enter') handleConfirm();
              if (e.key === 'Escape') onClose();
            }}
            placeholder="Section name…"
            class="w-full px-2 py-1.5 rounded bg-neutral-700 text-neutral-200 border border-neutral-600 text-sm focus:outline-none focus:border-blue-500 placeholder:text-neutral-500"
          />
          {error && <p class="text-red-400 text-xs mt-1.5">{error}</p>}
        </div>
        <div class="flex justify-end gap-2 px-4 py-3 border-t border-neutral-700">
          <button
            onClick={onClose}
            class="px-3 py-1 rounded text-xs bg-neutral-700 hover:bg-neutral-600 text-neutral-300 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            class="px-3 py-1 rounded text-xs bg-blue-700 hover:bg-blue-600 text-white transition-colors"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}

export function LibraryPanel({ onInsert, onStatus, getEditorContent, getEditorSelection }: LibraryPanelProps) {
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [loading, setLoading] = useState(false);
  const [insertingPath, setInsertingPath] = useState<string | null>(null);
  const [error, setError] = useState('');

  // Save form state
  const [showSaveForm, setShowSaveForm] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveDialog, setSaveDialog] = useState<SaveDialog | null>(null);
  const [saving, setSaving] = useState(false);

  const closeSaveForm = () => {
    setShowSaveForm(false);
    setSaveName('');
  };

  // New section dialog state
  const [showNewSection, setShowNewSection] = useState(false);
  const [newSectionError, setNewSectionError] = useState('');

  const openNewSection = () => {
    setNewSectionError('');
    setShowNewSection(true);
  };

  const handleCreateSection = (name: string) => {
    setCategories(prev => [...prev, name].sort());
    setSelectedCategory(name);
    setShowNewSection(false);
  };

  useEffect(() => {
    setLoading(true);
    fetchLibrary()
      .then(fetched => {
        setItems(fetched);
        const cats = Array.from(new Set(fetched.map(i => i.category))).sort();
        setCategories(cats);
        setError('');
      })
      .catch(() => setError('Failed to load library'))
      .finally(() => setLoading(false));
  }, []);

  const filteredItems = selectedCategory === 'All'
    ? items
    : items.filter(i => i.category === selectedCategory);

  const handleInsert = async (item: LibraryItem) => {
    setInsertingPath(item.path);
    try {
      const raw = await fetchLibraryItem(item.path);

      let content: string;
      if (item.path.endsWith('.xml')) {
        if (!raw.includes('<fmxmlsnippet') || !raw.includes('<Step')) {
          onStatus(`Insert failed: "${item.name}" is not a valid fmxmlsnippet`);
          return;
        }
        content = xmlToHr(raw);
        if (content.startsWith('# XML Parse Error:')) {
          onStatus(`Insert failed: "${item.name}" — ${content.replace('# XML Parse Error: ', '')}`);
          return;
        }
        if (!content.trim()) {
          onStatus(`Insert failed: "${item.name}" contains no script steps`);
          return;
        }
      } else {
        content = raw;
      }

      onInsert(content);
      onStatus(`Inserted from library: ${item.name}`);
    } catch {
      onStatus(`Failed to load: ${item.name}`);
    } finally {
      setInsertingPath(null);
    }
  };

  // Called when the blue Save button (next to name input) is clicked
  const handleSaveClick = () => {
    if (!saveName.trim() || selectedCategory === 'All') return;
    setSaveDialog({
      everything: getEditorContent(),
      selection: getEditorSelection(),
    });
  };

  // Called when user picks an option in the save dialog
  const handleSaveConfirm = async (content: string) => {
    setSaveDialog(null);
    if (!content.trim()) {
      onStatus('Nothing to save');
      return;
    }
    setSaving(true);
    const safeName = saveName.trim().replace(/[/\\?%*:|"<>]/g, '-');
    const safeCategory = selectedCategory.replace(/[/\\?%*:|"<>]/g, '-');
    const ext = content.trim().startsWith('<') ? '.xml' : '.md';
    const itemPath = `${safeCategory}/${safeName}${ext}`;
    try {
      await saveLibraryItem(itemPath, content);
      const size = formatSize(new TextEncoder().encode(content).byteLength);
      onStatus(`Saved: ${itemPath} (${size})`);
      setShowSaveForm(false);
      setSaveName('');
      const fetched = await fetchLibrary();
      setItems(fetched);
      const cats = Array.from(new Set(fetched.map(i => i.category))).sort();
      setCategories(cats);
    } catch {
      onStatus('Failed to save to library');
    } finally {
      setSaving(false);
    }
  };

  const canSave = saveName.trim() !== '' && selectedCategory !== 'All';

  return (
    <div class="flex flex-col h-full bg-neutral-900 text-neutral-300 text-xs">
      {/* Header */}
      <div class="flex items-center gap-2 px-3 py-2 border-b border-neutral-700 shrink-0">
        <span class="font-semibold text-neutral-200 text-sm">Library</span>
        <div class="flex-1" />
        <button
          onClick={() => showSaveForm ? closeSaveForm() : setShowSaveForm(true)}
          class={`px-2 py-0.5 rounded transition-colors ${
            showSaveForm
              ? 'bg-neutral-600 text-neutral-200'
              : 'bg-neutral-700 hover:bg-neutral-600 text-neutral-300'
          }`}
        >
          Save
        </button>
      </div>

      {/* Category filter */}
      <div class="px-3 py-2 border-b border-neutral-700 shrink-0">
        <select
          value={selectedCategory}
          onChange={e => {
            const val = (e.target as HTMLSelectElement).value;
            if (val === '__new__') {
              // Reset the select back to current category; open dialog instead
              (e.target as HTMLSelectElement).value = selectedCategory;
              openNewSection();
            } else {
              setSelectedCategory(val);
            }
          }}
          class="w-full px-2 py-1 rounded bg-neutral-700 text-neutral-200 border border-neutral-600 text-xs focus:outline-none focus:border-blue-500"
        >
          <option value="All">All</option>
          {categories.map(cat => (
            <option key={cat} value={cat}>{cat}</option>
          ))}
          <option disabled>──────────</option>
          <option value="__new__">New section…</option>
        </select>
      </div>

      {/* Save form — revealed below category select */}
      {showSaveForm && (
        <div class="px-3 py-2 border-b border-neutral-700 shrink-0 space-y-1.5">
          <div class="flex gap-1.5 items-center">
            <input
              type="text"
              autoFocus
              onInput={e => setSaveName((e.currentTarget as HTMLInputElement).value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && canSave) handleSaveClick();
                if (e.key === 'Escape') closeSaveForm();
              }}
              placeholder="Name…"
              class="flex-1 min-w-0 px-2 py-1 rounded bg-neutral-700 text-neutral-200 border border-neutral-600 text-xs focus:outline-none focus:border-blue-500 placeholder:text-neutral-500"
            />
            <button
              onClick={handleSaveClick}
              disabled={!canSave || saving}
              class="shrink-0 px-3 py-1 rounded bg-blue-700 hover:bg-blue-600 text-white text-xs transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? '…' : 'Save'}
            </button>
            <button
              onClick={closeSaveForm}
              title="Cancel"
              class="shrink-0 text-neutral-500 hover:text-neutral-300 transition-colors leading-none"
            >
              ✕
            </button>
          </div>
          {selectedCategory === 'All' && (
            <p class="text-neutral-500 text-xs">Select a category above to enable saving.</p>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div class="px-3 py-1 text-xs shrink-0 text-red-400">{error}</div>
      )}

      {/* Item list */}
      <div class="flex-1 overflow-y-auto min-h-0" style="scrollbar-gutter: stable">
        {loading && (
          <div class="px-3 py-4 text-neutral-500">Loading...</div>
        )}
        {!loading && filteredItems.length === 0 && (
          <div class="px-3 py-4 text-neutral-500">
            {items.length === 0 ? 'No library items found' : 'No items in this category'}
          </div>
        )}
        {!loading && filteredItems.map(item => (
          <div
            key={item.path}
            class="flex items-center gap-2 px-3 py-1.5 border-b border-neutral-800 hover:bg-neutral-800 transition-colors"
          >
            <div class="flex-1 min-w-0">
              <span class="text-neutral-200 truncate block" title={item.path}>
                {item.name}
              </span>
              {selectedCategory === 'All' && (
                <span class="text-neutral-500">{item.category}</span>
              )}
            </div>
            <button
              onClick={() => handleInsert(item)}
              disabled={insertingPath === item.path}
              title={`Insert ${item.name} into editor`}
              class="shrink-0 px-2 py-0.5 rounded bg-neutral-700 hover:bg-neutral-600 text-neutral-300 transition-colors disabled:opacity-50"
            >
              {insertingPath === item.path ? '...' : 'Insert'}
            </button>
          </div>
        ))}
      </div>

      {/* New section dialog */}
      {showNewSection && (
        <NewSectionDialog
          categories={categories}
          error={newSectionError}
          onError={setNewSectionError}
          onCreate={handleCreateSection}
          onClose={() => setShowNewSection(false)}
        />
      )}

      {/* Save dialog */}
      {saveDialog && (
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div class="bg-neutral-800 rounded-lg shadow-xl w-72 max-w-[90vw]">
            <div class="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
              <h2 class="text-sm font-semibold text-neutral-200">Save to Library</h2>
              <button
                onClick={() => setSaveDialog(null)}
                class="text-neutral-400 hover:text-neutral-200 text-lg leading-none"
              >
                &times;
              </button>
            </div>
            <div class="px-4 py-3 text-xs text-neutral-400 space-y-1">
              <p>
                Save <span class="text-neutral-100 font-medium">"{saveName.trim()}"</span>
                {' '}to <span class="text-neutral-100 font-medium">{selectedCategory}/</span>
              </p>
              {!saveDialog.selection && (
                <p class="text-neutral-500">No text is selected — full editor content will be saved.</p>
              )}
            </div>
            <div class="flex justify-end gap-2 px-4 py-3 border-t border-neutral-700">
              <button
                onClick={() => setSaveDialog(null)}
                class="px-3 py-1 rounded text-xs bg-neutral-700 hover:bg-neutral-600 text-neutral-300 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleSaveConfirm(saveDialog.everything)}
                class="px-3 py-1 rounded text-xs bg-blue-700 hover:bg-blue-600 text-white transition-colors"
              >
                Save Everything
              </button>
              {saveDialog.selection && (
                <button
                  onClick={() => handleSaveConfirm(saveDialog.selection!)}
                  class="px-3 py-1 rounded text-xs bg-blue-700 hover:bg-blue-600 text-white transition-colors"
                >
                  Selection Only
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
