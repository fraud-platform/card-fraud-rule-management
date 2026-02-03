async function main() {
  try {
    // Read stdin
    const chunks = [];
    for await (const chunk of process.stdin) {
      chunks.push(chunk);
    }
    
    const toolArgs = JSON.parse(Buffer.concat(chunks).toString());
    
    // Extract file path from various possible field names
    const readPath = 
      toolArgs.tool_input?.file_path || 
      toolArgs.tool_input?.path || 
      toolArgs.tool_input?.filepath ||
      toolArgs.tool_input?.target_path ||
      "";
    
    // Normalize path for comparison
    const normalizedPath = readPath.toLowerCase().replace(/\\/g, '/');
    
    // List of protected file patterns
    const blockedPatterns = [
      '.env',
      '.env.local',
      '.env.development',
      '.env.production',
      '.env.test',
      '.secrets',
      '.key',
      '.pem',
      '.p12',
      '.pfx',
      'credentials',
      'secret',
      'password',
      'private-key',
      'privatekey',
      'id_rsa',
      'id_dsa',
      'id_ecdsa',
      'id_ed25519',
      '.npmrc',
      '.pypirc'
    ];
    
    // Check if any blocked pattern appears in the path
    const isBlocked = blockedPatterns.some(pattern => 
      normalizedPath.includes(pattern.toLowerCase())
    );
    
    if (isBlocked) {
      // Write error to stdout (this gets passed back to Claude)
      console.log(JSON.stringify({
        error: `🔒 ACCESS DENIED: Cannot access ${readPath}`,
        blocked: true,
        reason: "This file contains sensitive information and is protected by security hooks."
      }));
      process.exit(1); // Exit with error code
    }
    
    // Allow the operation - output nothing to stdout
    process.exit(0);
    
  } catch (err) {
    console.log(JSON.stringify({
      error: `Security hook error: ${err.message}`,
      blocked: true
    }));
    process.exit(1);
  }
}

main();