import { createFileRoute } from "@tanstack/react-router";
import { Workspace } from "@/components/research/workspace";

export const Route = createFileRoute("/research/$conversationId")({
  component: ConversationRoute,
});

function ConversationRoute() {
  const { conversationId } = Route.useParams();
  return <Workspace conversationId={conversationId} />;
}
