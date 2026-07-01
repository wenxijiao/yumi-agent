import 'package:yumi_sdk/yumi_sdk.dart';

void initYumi() {
  final agent = YumiAgent(
    AgentOptions(edgeName: 'My Dart App'),
  );
  agent.register(
    RegisterOptions(
      name: 'hello',
      description: 'Say hello to someone',
      parameters: [
        ToolParameter(
          name: 'name',
          typeName: 'string',
          description: 'Person to greet',
        ),
      ],
      handler: (args) {
        final n = args.string('name');
        if (n.isEmpty) return 'Hello, World!';
        return 'Hello, $n!';
      },
      // Read-only tools can opt in to proactive messaging:
      // allowProactive: true,
      // proactiveContext: true,
    ),
  );

  // Example tool — replace with your own. Pinned mode keeps its schema
  // exposed to the model every turn so you can confirm the edge is connected.
  agent.register(
    RegisterOptions(
      name: 'ping',
      description: 'Ping the edge and echo a message back',
      mode: 'pinned',
      parameters: [
        ToolParameter(
          name: 'message',
          typeName: 'string',
          description: 'Text to echo back.',
        ),
      ],
      handler: (args) {
        final message = args.string('message');
        return 'pong: ${message.isEmpty ? 'hello' : message}';
      },
    ),
  );

  agent.runInBackground();
}
