"""
Basic module for tracking API metrics.

For this initial version of the Master's Thesis (MVP), we are using a simple
in-memory approach to count basic traffic.

The plan for the advanced metrics that would need to be implemented in a future
production phase, to monitor the infrastructure, API usage and the performance
of the Artificial Intelligence model (RAG), is designed and documented in this
file.
"""

# Global in-memory dictionary that stores the current metrics.
# Note: when the container restarts, this counter goes back to zero. For a real
# production environment, this should be connected to a temporary datastore
# (such as Redis) or to a metrics system such as Prometheus.
metrics = {"total_requests": 0}


# =====================================================================
# ROADMAP: Proposed metrics for future work
# =====================================================================
#
# 1. Infrastructure metrics (server performance):
#    - CPU and RAM usage.
#    - Disk read/write (I/O) and network usage.
#    - Container uptime.
#
# 2. API usage metrics:
#    - Response time and throughput.
#    - Error rate (percentage of failing requests).
#    - User feedback on the response.
#    - Clustering and classification of queries to understand what people
#      search for most and optimize those flows.
#
# 3. AI Agent / RAG engine metrics:
#    - Total number of viability reports generated.
#    - Retriever latency (time taken by the vector search).
#    - LLM latency (time taken by the model to generate the text).
#    - Number of legal fragments (chunks) retrieved per query.
#    - Accuracy of regulatory citations (citations returned vs. verified).
# =====================================================================
