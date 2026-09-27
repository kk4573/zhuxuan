/**
 * 竹喧 · 「加词时自动填充」规则测试
 *
 * 从 web/app.js 里把 shouldFill() 抠出来直接执行 —— 测的是真代码，不是复刻的逻辑。
 *
 *     node tests/check_autofill.js
 */
const fs = require('fs');
const path = require('path');

// 前端已按视图拆成多个文件，把 web/js/ 全读进来一起找
const JSDIR = path.join(__dirname, '..', 'web', 'js');
const src = fs.readdirSync(JSDIR)
  .filter((f) => f.endsWith('.js'))
  .map((f) => fs.readFileSync(path.join(JSDIR, f), 'utf8'))
  .join('\n');
const m = src.match(/function shouldFill\(autoFilled, key, currentValue\) \{[\s\S]*?\n\}/);
if (!m) {
  console.error('没在 app.js 里找到 shouldFill 函数（是不是被改名了？）');
  process.exit(1);
}
eval(m[0]);                                  // 定义 shouldFill

let ok = 0, fail = 0;
function check(label, cond, extra) {
  if (cond) { ok++; console.log('  [ok]    ' + label); }
  else { fail++; console.log('  [FAIL]  ' + label + '   ' + JSON.stringify(extra)); }
}

// 复刻 submit 里的填充动作（真实代码就是这个判断）
function fill(state, key, value) {
  if (!shouldFill(state.auto, key, state.fields[key])) return state;
  const next = {
    auto: Object.assign({}, state.auto),
    fields: Object.assign({}, state.fields),
  };
  next.fields[key] = value;
  next.auto[key] = true;
  return next;
}

function blank() {
  return { auto: { cn: false, pos: false, ph: false }, fields: { cn: '', pos: '', ph: '' } };
}

console.log('— 你报的那个场景：打 cry 停一下，接着打成 crystal —');
let st = blank();
st = fill(st, 'cn', '哭；喊叫'); st = fill(st, 'pos', 'v.'); st = fill(st, 'ph', 'kraɪ');
console.log('    输入 cry   → ' + JSON.stringify(st.fields));
st = fill(st, 'cn', '水晶；结晶'); st = fill(st, 'pos', 'n.'); st = fill(st, 'ph', 'ˈkrɪstl');
console.log('    输入 crystal → ' + JSON.stringify(st.fields));
check('后面的查询会覆盖前面的自动填充（这就是修复的点）',
      st.fields.cn === '水晶；结晶' && st.fields.pos === 'n.', st.fields);

console.log('\n— 空字段当然要填 —');
let st2 = blank();
check('空的中文释义 → 填', shouldFill(st2.auto, 'cn', st2.fields.cn));

console.log('\n— 用户自己改过的，不许覆盖 —');
let st3 = blank();
st3 = fill(st3, 'cn', '水晶');
st3.auto.cn = false;                       // 用户手动改了一下
check('手改过的字段 → 不再自动覆盖', !shouldFill(st3.auto, 'cn', st3.fields.cn));
check('但没碰过的字段照常自动填', shouldFill(st3.auto, 'pos', st3.fields.pos));

console.log('\n— 手改后又清空了，应当恢复自动填充 —');
check('清空的字段 → 重新自动填', shouldFill(st3.auto, 'cn', '   '));

console.log('\n— 编辑已有单词：字段是库里的值，不该被冲掉 —');
let st4 = { auto: { cn: false, pos: false, ph: false }, fields: { cn: '沙漠，荒漠', pos: 'n.', ph: '' } };
check('库里已有释义 → 自动查词不动它', !shouldFill(st4.auto, 'cn', st4.fields.cn));
check('库里的音标是空的 → 允许补上', shouldFill(st4.auto, 'ph', st4.fields.ph));

console.log('\n结果：' + ok + ' 通过 / ' + fail + ' 失败');
process.exit(fail ? 1 : 0);
