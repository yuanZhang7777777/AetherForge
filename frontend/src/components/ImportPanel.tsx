import { useEffect, useRef, useState, type DragEvent, type InputHTMLAttributes } from "react";

import { uploadPath, type UploadResult } from "../api";
import type { ImportMode, SkuImportResult } from "../types";

const folderInputProps = { webkitdirectory: "" } as InputHTMLAttributes<HTMLInputElement>;
const acceptedTypes = ".jpg,.jpeg,.png,.webp,.txt";

type DropEntry = {
  isFile: boolean;
  isDirectory: boolean;
  fullPath: string;
  file?: (success: (file: File) => void, error?: (error: DOMException) => void) => void;
  createReader?: () => { readEntries: (success: (entries: DropEntry[]) => void, error?: (error: DOMException) => void) => void };
};

async function filesFromEntry(entry: DropEntry): Promise<File[]> {
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((resolve, reject) => entry.file?.(resolve, reject));
    Object.defineProperty(file, "webkitRelativePath", { configurable: true, value: entry.fullPath.replace(/^\/+/, "") });
    return [file];
  }
  if (!entry.isDirectory || !entry.createReader) return [];
  const reader = entry.createReader();
  const children: DropEntry[] = [];
  while (true) {
    const page = await new Promise<DropEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (!page.length) break;
    children.push(...page);
  }
  return (await Promise.all(children.map(filesFromEntry))).flat();
}

export async function collectDroppedFiles(dataTransfer: DataTransfer) {
  const entries = Array.from(dataTransfer.items ?? [])
    .map((item) => (item as unknown as { webkitGetAsEntry?: () => DropEntry | null }).webkitGetAsEntry?.() ?? null)
    .filter((entry): entry is DropEntry => Boolean(entry));
  return entries.length ? (await Promise.all(entries.map(filesFromEntry))).flat() : Array.from(dataTransfer.files ?? []);
}

export function ImportPanel({
  onUpload,
  onSkuImport,
  onImported,
  disabled,
  aiRecognitionEnabled,
  onAiRecognitionChange,
}: {
  onUpload: (files: File[], mode: ImportMode) => Promise<UploadResult>;
  onSkuImport: (skus: string[], mode: ImportMode) => Promise<SkuImportResult>;
  onImported: () => void;
  disabled?: boolean;
  aiRecognitionEnabled?: boolean;
  onAiRecognitionChange?: (checked: boolean) => Promise<unknown>;
}) {
  const imagePicker = useRef<HTMLInputElement>(null);
  const folderPicker = useRef<HTMLInputElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [skuText, setSkuText] = useState("");
  const [skuErrors, setSkuErrors] = useState<string[]>([]);
  const [skuLoadingMode, setSkuLoadingMode] = useState<ImportMode | null>(null);
  const [fileLoadingMode, setFileLoadingMode] = useState<ImportMode | null>(null);
  const skuLines = () => skuText.split(/\s+/).map((item) => item.trim()).filter(Boolean);
  const addFiles = (nextFiles: File[]) => setFiles((current) => {
    const merged = new Map(current.map((file) => [`${uploadPath(file)}:${file.size}:${file.lastModified}`, file]));
    nextFiles.forEach((file) => merged.set(`${uploadPath(file)}:${file.size}:${file.lastModified}`, file));
    return Array.from(merged.values());
  });
  const dropFiles = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    addFiles(await collectDroppedFiles(event.dataTransfer));
  };
  const uploadFiles = async (mode: ImportMode) => {
    setFileLoadingMode(mode);
    try {
      if (mode === "auto" && !aiRecognitionEnabled && onAiRecognitionChange) await onAiRecognitionChange(true);
      const result = await onUpload(files, mode);
      const rejected = new Set(result.rejected.map((item) => item.filename));
      setFiles((current) => current.filter((file) => rejected.has(uploadPath(file))));
      if (!result.rejected.length) onImported();
    } catch {
      // The workbench keeps pending files visible for a retry.
    } finally {
      setFileLoadingMode(null);
    }
  };
  const importSkuList = async (mode: ImportMode) => {
    const skus = skuLines().slice(0, 50);
    if (!skus.length) return;
    setSkuLoadingMode(mode);
    try {
      if (mode === "auto" && !aiRecognitionEnabled && onAiRecognitionChange) await onAiRecognitionChange(true);
      const result = await onSkuImport(skus, mode);
      const failed = result.items.filter((item) => item.status === "failed");
      // 加载后保留已填 SKU，方便继续加载/补错，不清空输入框
      setSkuErrors(failed.map((item) => `${item.sku}：${skuErrorMessage(item.errorCode)}`));
      if (!failed.length) onImported();
    } catch {
      // The mutation owner renders transport/auth errors; do not lose the typed SKU list.
    } finally {
      setSkuLoadingMode(null);
    }
  };
  const imageFiles = files.filter((file) => !uploadPath(file).toLowerCase().endsWith(".txt"));
  const txtCount = files.length - imageFiles.length;

  return <section className="surface overflow-visible p-3" aria-label="添加商品面板">
    <div className="grid gap-3 xl:grid-cols-[1fr_auto_1fr]">
      <div className="min-w-0 rounded-xl border border-slate-100 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-800">图片 / 文件夹</h2>
          <p className="text-xs text-slate-500">{files.length ? `已选择 ${imageFiles.length} 张图片${txtCount ? `、${txtCount} 个 TXT` : ""}` : "尚未选择图片"}</p>
        </div>
        <div className="mt-3 rounded-xl border-2 border-dashed border-indigo-200 bg-indigo-50/40 px-4 py-4 text-center transition hover:border-indigo-300 hover:bg-indigo-50/60" onDragOver={(event) => event.preventDefault()} onDrop={dropFiles}>
          <p className="font-medium text-slate-700">拖入图片或文件夹</p>
          <p className="mt-1 text-xs text-slate-500">JPEG、PNG、WebP、UTF-8 TXT</p>
          <div className="relative mt-3 inline-block">
            <button className="secondary-button min-h-9 px-3" type="button" aria-controls="asset-picker-menu" aria-expanded={pickerOpen} onClick={() => setPickerOpen((open) => !open)}>选择图片/文件夹</button>
            {pickerOpen && <div id="asset-picker-menu" role="menu" aria-label="添加素材方式" className="absolute left-1/2 z-10 mt-2 w-48 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-2 text-left shadow-lg">
              <button className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50" role="menuitem" type="button" onClick={() => imagePicker.current?.click()}>选择图片</button>
              <button className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50" role="menuitem" type="button" onClick={() => folderPicker.current?.click()}>选择文件夹</button>
            </div>}
          </div>
        </div>
      <input ref={imagePicker} className="sr-only" aria-label="选择图片" type="file" multiple accept={acceptedTypes} onChange={(event) => { addFiles(Array.from(event.target.files ?? [])); event.currentTarget.value = ""; }} />
      <input ref={folderPicker} className="sr-only" aria-label="选择文件夹" type="file" multiple accept={acceptedTypes} {...folderInputProps} onChange={(event) => { addFiles(Array.from(event.target.files ?? [])); event.currentTarget.value = ""; }} />
      {imageFiles.length > 0 && <div className="mt-4 grid grid-cols-5 gap-2 sm:grid-cols-8">{imageFiles.map((file, index) => <PendingImage key={`${uploadPath(file)}:${file.size}:${file.lastModified}`} file={file} index={index} />)}</div>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="primary-button" disabled={disabled || !files.length || Boolean(fileLoadingMode)} onClick={() => void uploadFiles("organize")}>{fileLoadingMode === "organize" ? "导入中…" : "导入后整理"}</button>
        <button className="secondary-button" disabled={disabled || !files.length || Boolean(fileLoadingMode)} onClick={() => void uploadFiles("auto")}>{fileLoadingMode === "auto" ? "导入中…" : "导入并自动出图"}</button>
        {files.length > 0 && <button className="text-sm font-semibold text-slate-600" type="button" onClick={() => setFiles([])}>清空</button>}
      </div>
      </div>
      <div className="flex items-center justify-center gap-1 self-stretch rounded-xl border border-slate-100 px-3 py-2 xl:flex-col">
        <label className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600" title="开启后用 AI 识别商品名称与信息，与你填写的内容融合（你填的优先）"><input aria-label="AI 商品识别" className="size-4 accent-indigo-600" type="checkbox" checked={aiRecognitionEnabled ?? false} disabled={disabled} onChange={(event) => { void onAiRecognitionChange?.(event.target.checked); }} />AI 识别</label>
        <p className="hidden text-[11px] leading-tight text-slate-400 xl:block xl:max-w-20 xl:text-center">导入并自动出图时自动开启</p>
      </div>
      <div className="min-w-0 rounded-xl border border-slate-100 p-3">
        <label className="block text-sm font-medium text-slate-700"><span className="mb-2 block">ERP SKU</span><textarea className="min-h-20" value={skuText} onChange={(event) => { setSkuText(event.target.value); setSkuErrors([]); }} placeholder="每行或空格分隔，单次最多 50 个" /></label>
        {skuErrors.length > 0 && <ul className="mt-3 space-y-1 text-sm text-amber-800">{skuErrors.map((message) => <li key={message}>{message}</li>)}</ul>}
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="primary-button" disabled={disabled || !skuLines().length || Boolean(skuLoadingMode)} onClick={() => void importSkuList("organize")}>{skuLoadingMode === "organize" ? "加载中…" : "加载 SKU"}</button>
          <button className="secondary-button" disabled={disabled || !skuLines().length || Boolean(skuLoadingMode)} onClick={() => void importSkuList("auto")}>{skuLoadingMode === "auto" ? "加载中…" : "加载 SKU 并自动出图"}</button>
        </div>
      </div>
    </div>
  </section>;
}

function skuErrorMessage(code: string | null | undefined) {
  return ({ sku_not_found: "SKU 不存在或无可用商品图片", catalog_unavailable: "ERP 商品服务暂不可用", catalog_image_invalid: "商品图片无法导入", archive_failed: "商品图片归档失败", project_locked: "项目当前不可导入", login_expired: "登录已过期，请重新登录后导入", project_image_limit: "每个项目最多 100 张图片" } as Record<string, string>)[code ?? ""] ?? "导入失败，请重试";
}

function PendingImage({ file, index }: { file: File; index: number }) {
  const [source] = useState(() => typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : "data:image/gif;base64,R0lGODlhAQABAAAAACw=");
  useEffect(() => () => { if (source.startsWith("blob:") && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(source); }, [source]);
  return <img className="aspect-square w-full rounded-lg border border-slate-200 object-cover" src={source} alt={`待导入商品图 ${index + 1}`} />;
}
