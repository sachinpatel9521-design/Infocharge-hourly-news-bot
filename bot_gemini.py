response = client.models.generate_content(
    model=model,
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0.25,
        max_output_tokens=1800,
        tools=[
            types.Tool(
                google_search=types.GoogleSearch()
            )
        ],
    ),
)
