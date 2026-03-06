import { useRef, useEffect, useState } from 'preact/hooks';
import * as monaco from 'monaco-editor';
import { registerFileMakerLanguage, attachDiagnostics, LANGUAGE_ID } from './language/filemaker-script';
import { editorConfig } from './editor.config';
import { fetchStepCatalog } from '@/api/client';
import type { StepCatalogEntry } from '@/converter/catalog-types';
import type { FMContext } from '@/context/types';

// Configure Monaco workers
self.MonacoEnvironment = {
  getWorker(_: unknown, _label: string) {
    return new Worker(
      new URL('monaco-editor/esm/vs/editor/editor.worker.js', import.meta.url),
      { type: 'module' },
    );
  },
};

interface EditorPanelProps {
  value: string;
  onChange: (value: string) => void;
  context: FMContext | null;
}

export function EditorPanel({ value, onChange, context }: EditorPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const [catalog, setCatalog] = useState<StepCatalogEntry[]>([]);

  // Fetch step catalog for autocomplete and diagnostics
  useEffect(() => {
    fetchStepCatalog()
      .then(setCatalog)
      .catch(() => {
        // Catalog not available — autocomplete/diagnostics won't have step data
      });
  }, []);

  // Register language once catalog is loaded
  useEffect(() => {
    registerFileMakerLanguage(catalog.length > 0 ? catalog : undefined);
  }, [catalog]);

  // Create editor
  useEffect(() => {
    if (!containerRef.current) return;

    const editor = monaco.editor.create(containerRef.current, {
      ...editorConfig,
      value,
      language: LANGUAGE_ID,
      theme: 'filemaker-dark',
      automaticLayout: true,
    });

    editorRef.current = editor;

    // Expose global trigger for FileMaker "Perform JavaScript in Web Viewer"
    (window as any).triggerEditorAction = (actionId: string) => {
      editor.trigger('fm', actionId, null);
    };

    // Listen for changes
    editor.onDidChangeModelContent(() => {
      onChange(editor.getValue());
    });

    // Attach diagnostics
    const diagDisposable = attachDiagnostics(editor, catalog);

    return () => {
      delete (window as any).triggerEditorAction;
      diagDisposable.dispose();
      editor.dispose();
      editorRef.current = null;
    };
  }, [containerRef.current]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync value from parent (e.g. when loading a script)
  useEffect(() => {
    const editor = editorRef.current;
    if (editor && editor.getValue() !== value) {
      editor.setValue(value);
    }
  }, [value]);

  // Update context-aware completions when context changes
  useEffect(() => {
    // Future: update completion providers with context data
    // (field references, layout names, script names, etc.)
  }, [context]);

  return (
    <div
      ref={containerRef}
      class="h-full w-full"
    />
  );
}
