import { executeSkill } from "./skills";

export { executeSkill };

export function followUser(platform, body) {
  return executeSkill({
    skill_id: "follow-user",
    platform,
    params: body,
  });
}

export function unfollowUser(platform, body) {
  return executeSkill({
    skill_id: "unfollow-user",
    platform,
    params: body,
  });
}

export function sendUserMessage(platform, body) {
  return executeSkill({
    skill_id: "send-dm",
    platform,
    params: body,
  });
}
