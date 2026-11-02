import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";
import { transformWithOxc } from "vite";

const source = await readFile(new URL("../../src/pages/admin/StudentDirectoryPage.jsx", import.meta.url), "utf8");
const ast = parse(source, { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true }, range: true });
const card = ast.body.find((node) => node.type === "FunctionDeclaration" && node.id.name === "StudentCard");
const { code } = await transformWithOxc(source.slice(...card.range), "StudentCard.jsx", { jsx: { runtime: "classic" } });
const render = runInNewContext(`${code}\nStudentCard`, {
  React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children }) },
  MobilePersonCard: "MobilePersonCard", PersonIdentity: "PersonIdentity", Badge: "Badge", StudentActions: "StudentActions",
  displayName: (student) => student.name,
  getAvatarSrcFromRecord: (student) => student.passport_photo_url,
  studentClassLabel: () => "Year 1",
  titleCase: (value) => value,
  formatDate: (value) => value,
});

test("student wrapper forwards controlled expansion without leaking it to lifecycle actions", () => {
  let expanded = false;
  const onExpandedChange = (next) => { expanded = next; };
  const props = { student: { name: "Test Student", status: "active" }, onExpandedChange, onLifecycle: () => {} };
  const collapsed = render({ ...props, expanded });
  assert.equal(collapsed.props.expanded, false);
  assert.equal(collapsed.props.onExpandedChange, onExpandedChange);
  collapsed.children[0].props.onClick();
  const opened = render({ ...props, expanded });
  assert.equal(opened.props.expanded, true);
  const actions = opened.children.at(-1).children[0];
  assert.equal(actions.props.onLifecycle, props.onLifecycle);
  assert.equal("onExpandedChange" in actions.props, false);
  assert.equal("expanded" in actions.props, false);
  opened.props.onExpandedChange(false);
  assert.equal(expanded, false);
});

test("student summary expands with Enter and Space and ignores other keys", () => {
  for (const key of ["Enter", " ", "Tab"]) {
    let expanded = false;
    let prevented = false;
    const row = render({ student: { name: "Test Student" }, expanded, onExpandedChange: (value) => { expanded = value; } });
    row.children[0].props.onKeyDown({ key, preventDefault: () => { prevented = true; } });
    assert.equal(expanded, key !== "Tab");
    assert.equal(prevented, key !== "Tab");
  }
});
