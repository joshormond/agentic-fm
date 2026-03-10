import { useMemo } from 'preact/hooks';
import { hrToXml } from '@/converter/hr-to-xml';
import type { FMContext } from '@/context/types';

interface XmlPreviewProps {
  hrText: string;
  context: FMContext | null;
}

export function XmlPreview({ hrText, context }: XmlPreviewProps) {
  const result = useMemo(() => hrToXml(hrText, context), [hrText, context]);

  return (
    <div class="flex flex-col h-full bg-neutral-900 border-t border-neutral-700">
      <div class="flex items-center justify-between px-3 py-1 bg-neutral-800 text-xs text-neutral-400 border-b border-neutral-700">
        <span>XML Preview</span>
        {result.errors.length > 0 && (
          <span class="text-yellow-400">{result.errors.length} warning(s)</span>
        )}
      </div>
      <pre class="flex-1 overflow-auto p-3 text-xs text-neutral-300 font-mono whitespace-pre leading-relaxed">
        {result.xml}
      </pre>
      {result.errors.length > 0 && (
        <div class="border-t border-neutral-700 px-3 py-2 text-xs">
          {result.errors.map((err, i) => (
            <div key={i} class="text-yellow-400">
              Line {err.line}: {err.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
