import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("people directory renders real photos with a neutral icon fallback", async () => {
  const source = await read("../../src/components/people/PeopleDirectory.jsx");

  assert.match(source, /avatarSrc && !imageFailed/);
  assert.match(source, /object-cover object-center/);
  assert.match(source, /onError=\{\(\) => setImageFailed\(true\)\}/);
  assert.match(source, /h-\[1\.125rem\] w-\[1\.125rem\]/);
  assert.doesNotMatch(source, /fallbackInitials|const initials/);
});

test("student, teacher and parent directory identities use shared avatar URL resolution", async () => {
  const [students, memberships] = await Promise.all([
    read("../../src/pages/admin/StudentDirectoryPage.jsx"),
    read("../../src/pages/admin/MembershipDirectoryPage.jsx"),
  ]);

  assert.equal(
    (students.match(/avatarSrc=\{getAvatarSrcFromRecord\(student\)\}/g) || []).length,
    2,
  );
  assert.equal(
    (memberships.match(/avatarSrc=\{getAvatarSrcFromRecord\(account\)\}/g) || []).length,
    4,
  );
});

test("printed report cards use the student passport or a blank structured photo area", async () => {
  const source = await read("../../src/components/shared/ReportCardPrintSheet.jsx");

  assert.match(source, /const studentPhoto = card\.student_passport_photo_url/);
  assert.match(source, /studentPhoto \? \(/);
  assert.match(source, /alt="Student passport"/);
  assert.match(source, /aria-label="Student photo not provided"/);
  assert.doesNotMatch(source, />No photo<\/div>/);
});
