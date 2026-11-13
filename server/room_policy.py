"""Require private encrypted rooms on the Sovereign Chat homeserver."""

from synapse.api.errors import SynapseError

ENCRYPTION = {"algorithm": "m.megolm.v1.aes-sha2"}
PRIVATE_STATE = {
    "m.room.encryption": ENCRYPTION,
    "m.room.join_rules": {"join_rule": "invite"},
    "m.room.guest_access": {"guest_access": "forbidden"},
    "m.room.history_visibility": {"history_visibility": "joined"},
}
PLAINTEXT_CONTENT = {
    "m.room.message", "m.sticker", "m.poll.start", "m.poll.response", "m.poll.end",
    "org.matrix.msc3381.poll.start", "org.matrix.msc3381.poll.response",
    "org.matrix.msc3381.poll.end",
}


class PrivateEncryptedRooms:
    def __init__(self, config, api):
        self.server_name = config["server_name"]
        api.register_third_party_rules_callbacks(
            on_create_room=self.on_create_room,
            check_event_allowed=self.check_event_allowed,
            check_visibility_can_be_modified=self.check_visibility,
        )

    def is_local(self, user_id):
        return isinstance(user_id, str) and user_id.startswith("@") and user_id.endswith(f":{self.server_name}")

    async def on_create_room(self, requester, config, is_requester_admin):
        if (
            not self.is_local(requester.user.to_string())
            or config.get("visibility", "private") != "private"
            or config.get("preset", "private_chat") not in {"private_chat", "trusted_private_chat"}
            or config.get("invite_3pid")
            or any(not self.is_local(user) for user in config.get("invite", []))
        ):
            raise SynapseError(403, "Only private rooms with local accounts are supported.")
        config.setdefault("creation_content", {})["m.federate"] = False
        config["initial_state"] = [
            event for event in config.get("initial_state", [])
            if event.get("type") not in PRIVATE_STATE
        ] + [
            {"type": name, "state_key": "", "content": content.copy()}
            for name, content in PRIVATE_STATE.items()
        ]

    async def check_event_allowed(self, event, state):
        if not self.is_local(event.sender) or event.type in PLAINTEXT_CONTENT:
            return False, None
        if event.type == "m.room.create":
            return event.content.get("m.federate") is False, None
        if event.type == "m.room.member" and not self.is_local(event.state_key):
            return False, None
        if event.type in PRIVATE_STATE:
            return event.state_key == "" and dict(event.content) == PRIVATE_STATE[event.type], None
        if event.type == "m.room.encrypted":
            encryption = state.get(("m.room.encryption", ""))
            return encryption is not None and encryption.content.get("algorithm") == ENCRYPTION["algorithm"], None
        return True, None

    async def check_visibility(self, room_id, state, visibility):
        return visibility == "private"
