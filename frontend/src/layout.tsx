import { useState, type ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, loadCurrentUser, logoutUser } from "./api";

export function Shell({ children }: { children: ReactNode }) {
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const logout = async () => {
    setLoggingOut(true);
    setLogoutError("");
    try {
      await logoutUser();
      window.location.assign("/login/");
    } catch {
      setLoggingOut(false);
      setLogoutError("退出登录失败，请重试。");
    }
  };
  return <div className="min-h-screen bg-blue-50/50 text-slate-900"><aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col border-r border-blue-100 bg-white px-4 py-5 lg:flex"><Brand /><Navigation /></aside><div className="lg:pl-60"><header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-blue-100 bg-blue-50/90 px-5 backdrop-blur lg:px-8"><p className="text-sm font-semibold text-blue-700">AetherForge · AI 出图平台</p><div className="flex items-center gap-3">{logoutError && <p className="text-sm text-rose-700" role="alert">{logoutError}</p>}<button className="text-sm font-semibold text-slate-600" type="button" disabled={loggingOut} onClick={() => void logout()}>退出登录</button><span className="grid size-8 place-items-center rounded-full bg-blue-900 text-xs font-semibold text-white">OP</span></div></header><nav className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-3 py-2 lg:hidden" aria-label="移动端主导航"><Navigation /></nav><main className="mx-auto max-w-7xl p-5 lg:p-8">{children}</main></div></div>;
}

function Brand() { return <Link to="/" className="mb-9 flex items-center gap-3 px-2 text-lg font-bold tracking-tight text-slate-950"><span className="grid size-8 place-items-center rounded-lg bg-blue-600 text-xs text-white">AF</span>AetherForge</Link>; }
function Navigation() { const currentUser = useQuery({ queryKey: ["current-user"], queryFn: loadCurrentUser, staleTime: 5 * 60_000, retry: false }); const admin = currentUser.data?.role === "admin"; return <div className="flex gap-1 lg:block lg:space-y-1"><NavLink end to="/" className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>工作台</NavLink><NavLink to="/projects/new" className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>新建项目</NavLink><NavLink to="/production" className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>生产队列</NavLink>{admin && <NavLink to="/admin/prompt-center" className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>Prompt 管理中心</NavLink>}</div>; }

export function PageHeading({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) { return <div className="mb-8 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><p className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">{eyebrow}</p><h1 className="text-3xl font-bold tracking-tight text-slate-950">{title}</h1></div>{action}</div>; }
export function userErrorMessage(error: unknown) { const message = error instanceof Error ? error.message : ""; if (/Product is being prepared/i.test(message)) return "商品正在处理，完成后再修改或重新生成"; if (/Cluster changed|refresh before saving/i.test(message)) return "商品信息刚刚更新，请刷新后再保存"; if (/Product is archived/i.test(message)) return "商品已归档，不能继续修改"; if (/forbidden/i.test(message)) return "没有权限访问"; return message || "请检查网络或稍后重试。"; }
export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) { const apiError = error instanceof ApiError ? error : undefined; const loginRequired = apiError?.authRequired || apiError?.status === 401; const title = loginRequired ? "登录已失效，请重新登录" : apiError?.status === 403 ? "没有权限访问" : apiError?.status && apiError.status >= 500 ? "服务器处理失败" : "操作失败"; return <section className="surface max-w-xl p-6" role="alert"><h2 className="font-semibold text-rose-700">{title}</h2><p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-600">{userErrorMessage(error)}</p><div className="mt-5 flex gap-2">{retry && <button className="secondary-button" onClick={retry}>重试</button>}{loginRequired && <a className="primary-button" href="/login/">重新登录</a>}</div></section>; }
export function EmptyState({ title, description }: { title: string; description: string }) { return <section className="surface grid min-h-56 place-items-center p-8 text-center"><div><h2 className="font-semibold">{title}</h2><p className="mt-2 text-sm text-slate-500">{description}</p></div></section>; }
export function statusText(status: string) { return ({ draft: "待配置", pending: "待预备生成", queued: "排队中", running: "生成中", processing: "生成中", completed: "已完成", ready: "预备完成", failed: "需处理" } as Record<string, string>)[status] ?? status; }
