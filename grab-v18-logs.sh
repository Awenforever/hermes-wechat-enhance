#!/bin/bash
# grab-v18-logs.sh — 抓取 v0.18 测试容器日志并分析
# 用法: bash /opt/data/skills/hermes-wechat-enhance/grab-v18-logs.sh [容器名]

CONTAINER="${1:-hermes-v18-test}"
OUTDIR="/opt/data/weekly-briefing/v18-test-logs/$(date +%Y-%m-%d_%H%M%S)"
mkdir -p "$OUTDIR"

echo "=== 抓取 v0.18 测试日志 ==="
echo "容器: $CONTAINER"
echo "输出: $OUTDIR"
echo ""

# 1. 全量 gateway 日志
docker logs "$CONTAINER" 2>&1 > "$OUTDIR/full-gateway.log"
echo "✅ 全量日志: $OUTDIR/full-gateway.log ($(wc -l < $OUTDIR/full-gateway.log) 行)"

# 2. 提取关键事件
echo "" > "$OUTDIR/analysis.txt"

# Footer 分析
echo "=== FOOTER 分析 ===" >> "$OUTDIR/analysis.txt"
grep -i "footer\|model='.*'\|\bhermes\b" "$OUTDIR/full-gateway.log" | grep -v "logger\|import\|WARNING.*hermes_alive" >> "$OUTDIR/analysis.txt" 2>/dev/null
echo "" >> "$OUTDIR/analysis.txt"

# /continue 分析
echo "=== /continue 分析 ===" >> "$OUTDIR/analysis.txt"
grep -i "/continue\|continue.*drain\|drain.*pending" "$OUTDIR/full-gateway.log" >> "$OUTDIR/analysis.txt" 2>/dev/null
echo "" >> "$OUTDIR/analysis.txt"

# 消息收发
echo "=== 消息收发 ===" >> "$OUTDIR/analysis.txt"
grep -i "inbound\|outbound\|Weixin queued\|send.*count=" "$OUTDIR/full-gateway.log" >> "$OUTDIR/analysis.txt" 2>/dev/null
echo "" >> "$OUTDIR/analysis.txt"

# Hook 加载
echo "=== Hook 加载 ===" >> "$OUTDIR/analysis.txt"
grep -i "hooks\|Loaded hook" "$OUTDIR/full-gateway.log" >> "$OUTDIR/analysis.txt" 2>/dev/null
echo "" >> "$OUTDIR/analysis.txt"

# 启动/错误
echo "=== 启动 & 错误 ===" >> "$OUTDIR/analysis.txt"
grep -i "Gateway Starting\|Gateway running\|✓ weixin\|error\|Error\|WARNING" "$OUTDIR/full-gateway.log" | head -30 >> "$OUTDIR/analysis.txt" 2>/dev/null

# 3. 摘要
echo ""
echo "=== 摘要 ==="
echo "总行数: $(wc -l < $OUTDIR/full-gateway.log)"
echo ""
echo "Footer 事件数: $(grep -c "footer\|model='\|Weixin queued send" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)"
echo "入站消息数: $(grep -c "inbound from=" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)"
echo "出站发送数: $(grep -c "queued send" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)"
echo "/continue 事件: $(grep -c "/continue" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)"
echo "错误数: $(grep -c "ERROR\|Error" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)"
echo ""
echo "详细分析: $OUTDIR/analysis.txt"

# 4. 快速判断
echo ""
echo "=== 快速判定 ==="
# 检查 footer 是否有 hermes (系统消息)
sys_count=$(grep -c "model='hermes'" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)
model_count=$(grep -c "model='deepseek" $OUTDIR/full-gateway.log 2>/dev/null || echo 0)
echo "系统消息(hermes): $sys_count"
echo "模型消息(deepseek): $model_count"
if [ "$sys_count" -gt 0 ] && [ "$model_count" -gt 0 ]; then
    echo "✅ 系统/模型区分正常"
elif [ "$model_count" -gt 0 ]; then
    echo "⚠️  只看到模型消息，可能所有消息都标记为模型"
elif [ "$sys_count" -gt 0 ]; then
    echo "⚠️  只看到系统消息，可能所有消息都标记为 hermes"
else
    echo "❌ 未检测到任何 footer"
fi

# Hook 检测
if grep -q "Loaded hook" "$OUTDIR/full-gateway.log" 2>/dev/null; then
    echo "✅ Hook 已加载"
else
    echo "❌ Hook 未加载 (缺少 --accept-hooks?)"
fi

# 启动通知
if grep -qi "就绪\|ready.*notif\|启动" "$OUTDIR/full-gateway.log" 2>/dev/null; then
    echo "✅ 检测到启动相关日志"
else
    echo "⚠️  未检测到启动通知"
fi