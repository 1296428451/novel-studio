// 安全解析接口响应：不假设响应一定是 JSON。
// 当服务端返回了 HTML（Flask 默认 404/405/500 页以 "<!doctype" 开头）时，
// 直接 r.json() 会抛 “'<', '<!doctype' ... is not valid JSON”。
// 这里先读文本，识别非 JSON 后给出可读的错误信息。
async function apijson(r) {
  let text = '';
  try {
    text = await r.text();
  } catch (_) {
    throw new Error('接口 ' + r.url + ' 读取响应失败');
  }
  if (text == null || text.trim() === '') return {};

  const head = text.trimStart().slice(0, 64).toLowerCase();
  if (head[0] === '<') {
    const tag = (text.trim().match(/^<([a-zA-Z0-9]+)/) || [])[1] || 'html';
    const picked = text.trim().replace(/[\r\n]+/g, ' ').slice(0, 120);
    throw new Error('接口 ' + r.url + ' 返回了 HTML 而非 JSON（HTTP ' + r.status +
      '，页面类型 <' + tag + '>）：' + picked);
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error('接口 ' + r.url + ' 返回的 JSON 解析失败（HTTP ' + r.status +
      '）：' + text.trim().replace(/[\r\n]+/g, ' ').slice(0, 120));
  }
}