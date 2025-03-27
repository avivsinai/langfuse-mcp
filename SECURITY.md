# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of Langfuse MCP seriously. If you discover a security vulnerability, please follow these steps:

1. **Do not disclose the vulnerability publicly** until it has been addressed by the maintainers.
2. Email the project maintainer directly at [avivsinai@gmail.com](mailto:avivsinai@gmail.com) with details about the vulnerability.
3. Include as much information as possible, such as:
   - A description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggestions for remediation if you have them

## What to Expect

- You will receive acknowledgment of your report within 48 hours.
- We will investigate and work to verify the issue.
- We will keep you informed of our progress.
- Once the issue is resolved, we will publicly acknowledge your responsible disclosure unless you request otherwise.

## Security Considerations

When using Langfuse MCP, be aware of the following security considerations:

1. **API Keys**: Keep your Langfuse API keys secure and do not expose them in client-side code or public repositories.
2. **Access Control**: The MCP server has access to your Langfuse data. Be mindful of who has access to the MCP server configuration.
3. **Data Sensitivity**: Consider what data is being stored in Langfuse and what information might be exposed through the MCP tools.

## Best Practices

- Regularly update to the latest version of Langfuse MCP
- Keep your dependencies up to date
- Use environment variables for sensitive configuration values
- Run the MCP server in a controlled environment 