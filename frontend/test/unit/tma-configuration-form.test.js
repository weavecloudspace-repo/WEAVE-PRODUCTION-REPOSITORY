import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { parse } from "espree";
import { transformWithOxc } from "vite";

const source = await readFile(
  new URL("../../src/features/tma/TmaPage.jsx", import.meta.url),
  "utf8",
);
const ast = parse(source, {
  ecmaVersion: "latest",
  sourceType: "module",
  ecmaFeatures: { jsx: true },
  range: true,
});
const component = ast.body.find(
  (node) =>
    node.type === "FunctionDeclaration" && node.id.name === "Configuration",
);
const { code } = await transformWithOxc(
  source.slice(...component.range),
  "Configuration.jsx",
  { jsx: { runtime: "classic" } },
);

function fixture() {
  const state = [];
  let cursor = 0;
  let saved;
  const renderComponent = runInNewContext(`${code}\nConfiguration`, {
    React: {
      createElement: (type, props, ...children) => ({
        type,
        props: props || {},
        children,
      }),
    },
    Select: "Select",
    Button: "Button",
    field: "",
    dateInput: () => "",
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [
        state[index],
        (value) => {
          state[index] = value;
        },
      ];
    },
  });
  const config = {
    academic_session_id: "session",
    academic_term_id: "term",
    term_open: true,
    scopes: [
      {
        academic_level_id: "ss1",
        curriculum_subject_id: "math1",
        level_name: "SS1",
        subject_name: "Maths",
      },
      {
        academic_level_id: "ss1",
        curriculum_subject_id: "english1",
        level_name: "SS1",
        subject_name: "English",
      },
      {
        academic_level_id: "ss2",
        curriculum_subject_id: "math2",
        level_name: "SS2",
        subject_name: "Maths",
      },
    ],
    components: [{ id: "ca1", name: "CA1", maximum_score: 10 }],
  };
  const render = () => {
    cursor = 0;
    return renderComponent({
      config,
      busy: false,
      onSave: (payload) => {
        saved = payload;
      },
    });
  };
  return { render, saved: () => saved };
}
const nodes = (node) =>
  !node || typeof node !== "object"
    ? []
    : Array.isArray(node)
      ? node.flatMap(nodes)
      : [node, ...nodes(node.children)];
const select = (tree, label) =>
  nodes(tree).find(
    (node) => node.type === "Select" && node.props.label === label,
  );

test("subject choices follow the separate level selector and changing level clears the subject", () => {
  const view = fixture();
  let tree = view.render();
  assert.equal(select(tree, "Subject").props.disabled, true);
  assert.equal(
    nodes(select(tree, "Academic level")).filter(
      (node) => node.type === "option",
    ).length,
    2,
  );
  select(tree, "Academic level").props.onChange("ss1");
  tree = view.render();
  assert.deepEqual(
    nodes(select(tree, "Subject"))
      .filter((node) => node.type === "option")
      .map((node) => node.props.value),
    ["math1", "english1"],
  );
  select(tree, "Subject").props.onChange("math1");
  select(tree, "Assessment component").props.onChange("ca1");
  tree = view.render();
  tree.props.onSubmit({ preventDefault() {} });
  assert.equal(view.saved().academic_level_id, "ss1");
  assert.equal(view.saved().curriculum_subject_id, "math1");
  select(tree, "Academic level").props.onChange("ss2");
  tree = view.render();
  assert.equal(select(tree, "Subject").props.value, "");
  assert.deepEqual(
    nodes(select(tree, "Subject"))
      .filter((node) => node.type === "option")
      .map((node) => node.props.value),
    ["math2"],
  );
  assert.equal(
    nodes(tree).find((node) => node.type === "Button").props.disabled,
    true,
  );
});
