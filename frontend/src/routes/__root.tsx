import { createRootRoute, Outlet } from "@tanstack/react-router";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";

export const Route = createRootRoute({
  component: RootComponent,
});

function RootComponent() {
  return (
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar />
      <SidebarInset className="overflow-hidden">
        <Outlet />
      </SidebarInset>
      <Toaster />
    </SidebarProvider>
  );
}
