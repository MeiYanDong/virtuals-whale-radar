import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatCompactNumber, formatShortDateTime } from "@/lib/format";

interface MinutePoint {
  minuteKey: number;
  spent: number;
  fee: number;
  tax: number;
  buyers: number;
}

export function MinuteChart({ data }: { data: MinutePoint[] }) {
  return (
    <div className="h-[320px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid stroke="rgba(36, 142, 147, 0.12)" vertical={false} />
          <XAxis
            dataKey="minuteKey"
            tickFormatter={(value: number) => formatShortDateTime(value)}
            stroke="rgba(24, 75, 82, 0.5)"
            tick={{ fontSize: 12 }}
          />
          <YAxis
            stroke="rgba(24, 75, 82, 0.5)"
            tick={{ fontSize: 12 }}
            tickFormatter={(value: number) => formatCompactNumber(value)}
          />
          <Tooltip
            cursor={{ fill: "rgba(36, 142, 147, 0.08)" }}
            contentStyle={{
              borderRadius: 20,
              border: "1px solid rgba(199, 221, 215, 0.9)",
              background: "rgba(255,255,255,0.96)",
              boxShadow: "0 24px 44px rgba(36,52,48,0.12)",
            }}
            formatter={(value, name) => [formatCompactNumber(Number(value ?? 0)), String(name)]}
            labelFormatter={(value) => formatShortDateTime(Number(value ?? 0))}
          />
          <Bar dataKey="spent" fill="var(--chart-1)" radius={[14, 14, 6, 6]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
