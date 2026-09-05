import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreateMonitor } from "@/hooks/use-monitors";

const FREQUENCIES = ["每天 09:00", "每周一 09:00", "每小时", "手动"];

const monitorSchema = z.object({
  name: z.string().min(1, "请输入监测对象").max(50, "名称过长"),
  subject: z.string().min(1, "请输入监测主题").max(200, "主题过长"),
  strategy: z.string().max(200, "策略过长").optional(),
  frequency: z.string().min(1, "请选择频率"),
  websites: z.string().min(1, "请输入至少一个监测网站"),
  questions: z.string().optional(),
});

type MonitorValues = z.infer<typeof monitorSchema>;

export function MonitorForm({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const createMonitor = useCreateMonitor();
  const form = useForm<MonitorValues>({
    resolver: zodResolver(monitorSchema),
    defaultValues: {
      name: "",
      subject: "",
      strategy: "",
      frequency: "每天 09:00",
      websites: "",
      questions: "",
    },
  });

  async function onSubmit(values: MonitorValues) {
    const questions = (values.questions ?? "")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const websites = values.websites
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const monitor = await createMonitor.mutateAsync({
      name: values.name,
      subject: values.subject,
      strategy: values.strategy ?? "",
      frequency: values.frequency,
      questions,
      websites,
    });
    onOpenChange(false);
    form.reset();
    await navigate({ to: "/monitor/$monitorId", params: { monitorId: monitor.id } });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新建监测</DialogTitle>
          <DialogDescription>长期盯住一个对象，持续发现变化并沉淀到时间轴。</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>监测对象</FormLabel>
                  <FormControl>
                    <Input placeholder="英伟达先进封装供应链" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="subject"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>监测主题</FormLabel>
                  <FormControl>
                    <Textarea placeholder="CoWoS 产能与供应商变化…" rows={2} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="strategy"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>监测策略（可选）</FormLabel>
                  <FormControl>
                    <Input placeholder="关注产能扩张、供应商变化、新合作方" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="frequency"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>执行频率</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="选择频率" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {FREQUENCIES.map((frequency) => (
                        <SelectItem key={frequency} value={frequency}>
                          {frequency}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="websites"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>监测网站（每行一个 URL）</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder={"https://nvidianews.nvidia.com\nhttps://www.tsmc.com"}
                      rows={2}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="questions"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>监测问题（每行一个，可选）</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="产能扩张&#10;供应商变化&#10;新合作方"
                      rows={3}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="submit" disabled={createMonitor.isPending}>
                {createMonitor.isPending ? "创建中…" : "创建"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
