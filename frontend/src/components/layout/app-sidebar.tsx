import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  Aperture,
  ArchiveRestore,
  BookOpen,
  Clapperboard,
  Compass,
  LayoutGrid,
  MessageSquarePlus,
  Radar,
  Settings,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useArchiveConversation,
  useConversations,
  useCreateConversation,
  useRestoreConversation,
} from "@/hooks/use-conversations";
import { cn } from "@/lib/utils";

const RUN_PHASE_LABELS: Record<string, string> = {
  planning: "制定检索计划",
  collecting: "收集材料",
  assessing: "评估证据",
  checkpointing: "提交结果",
};

export function AppSidebar() {
  const { conversationId } = useParams({ strict: false });
  const navigate = useNavigate();
  const { data: conversations, isLoading } = useConversations(false);
  const { data: archived } = useConversations(true);
  const createConversation = useCreateConversation();
  const archiveConversation = useArchiveConversation();
  const restoreConversation = useRestoreConversation();

  async function create() {
    const conversation = await createConversation.mutateAsync();
    await navigate({
      to: "/research/$conversationId",
      params: { conversationId: conversation.id },
    });
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Link to="/" className="flex items-center gap-2 px-1">
          <Aperture className="size-5 text-primary" />
          <span className="text-base font-bold tracking-tight group-data-[collapsible=icon]:hidden">
            知证<span className="ml-1 font-normal text-muted-foreground">情报研究工作台</span>
          </span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>工作区</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="工作台">
                  <Link to="/">
                    <LayoutGrid />
                    <span>工作台</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="深度调研">
                  <Link to="/research">
                    <Compass />
                    <span>深度调研</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="持续监测">
                  <Link to="/monitor">
                    <Radar />
                    <span>持续监测</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="事实核验">
                  <Link to="/fact-check">
                    <ShieldCheck />
                    <span>事实核验</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="媒体分析">
                  <Link to="/media">
                    <Clapperboard />
                    <span>媒体分析</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="情报资料库">
                  <Link to="/library">
                    <BookOpen />
                    <span>情报资料库</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="系统设置">
                  <Link to="/settings">
                    <Settings />
                    <span>系统设置</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>最近会话</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={create} tooltip="新建对话">
                  <MessageSquarePlus />
                  <span>新建对话</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {isLoading && (
                <div className="space-y-2 px-2">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-full" />
                </div>
              )}
              {conversations?.map((conversation) => (
                <SidebarMenuItem key={conversation.id}>
                  <SidebarMenuButton
                    asChild
                    isActive={conversation.id === conversationId}
                    tooltip={conversation.title}
                  >
                    <Link
                      to="/research/$conversationId"
                      params={{ conversationId: conversation.id }}
                    >
                      <span className="truncate">{conversation.title}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                        {conversation.run_status === "running"
                          ? RUN_PHASE_LABELS[conversation.run_phase ?? "planning"]
                          : conversation.status === "intake"
                            ? "待明确目标"
                            : ""}
                      </span>
                    </Link>
                  </SidebarMenuButton>
                  <SidebarMenuAction
                    showOnHover
                    className={cn("text-muted-foreground hover:text-destructive")}
                    aria-label={`归档 ${conversation.title}`}
                    onClick={() => archiveConversation.mutate(conversation.id)}
                  >
                    <Trash2 className="size-4" />
                  </SidebarMenuAction>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {(archived?.length ?? 0) > 0 && (
          <SidebarGroup>
            <SidebarGroupLabel>已归档 ({archived?.length ?? 0})</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {archived?.map((conversation) => (
                  <SidebarMenuItem key={conversation.id}>
                    <SidebarMenuButton
                      asChild
                      isActive={conversation.id === conversationId}
                      tooltip={conversation.title}
                    >
                      <Link
                        to="/research/$conversationId"
                        params={{ conversationId: conversation.id }}
                      >
                        <span className="truncate text-muted-foreground">{conversation.title}</span>
                      </Link>
                    </SidebarMenuButton>
                    <SidebarMenuAction
                      showOnHover
                      aria-label={`恢复 ${conversation.title}`}
                      onClick={() => restoreConversation.mutate(conversation.id)}
                    >
                      <ArchiveRestore className="size-4" />
                    </SidebarMenuAction>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        )}
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
          <span className="size-2 rounded-full bg-sky-500" />
          本地工作区
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
