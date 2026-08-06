import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { createProject } from "../api";
import { ErrorPanel, PageHeading, Shell } from "../layout";

export default function ProjectNew() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => createProject({ name }),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ["workspace"] });
      navigate(`/projects/${project.id}`);
    },
  });

  return <Shell>
    <PageHeading eyebrow="新建项目" title="创建出图项目" />
    <form className="mx-auto max-w-xl space-y-5" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
      <section className="surface p-6">
        <label className="block text-sm font-medium text-slate-700" htmlFor="project-name">
          <span className="mb-2 block">项目名称</span>
          <input id="project-name" value={name} placeholder="例如：八月家居新品" onChange={(event) => setName(event.target.value)} autoFocus />
        </label>
        <p className="mt-4 text-sm text-slate-500">创建后先添加商品，再在项目内设置平台、国家和出图风格。</p>
      </section>
      {create.isError && <ErrorPanel error={create.error} retry={() => create.mutate()} />}
      <button className="primary-button" disabled={!name.trim() || create.isPending} type="submit">
        {create.isPending ? "正在创建…" : "创建项目"}
      </button>
    </form>
  </Shell>;
}
