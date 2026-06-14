# Legalassist-AI API Reference Guide

Detailed guide to the REST API endpoints in the Legalassist-AI platform.

## Auth Endpoints

### POST /api/v1/auth/token
Exchange username and password for a JWT token.

### POST /api/v1/auth/revoke
Revoke a JWT token session.

## Case Endpoints

### GET /api/v1/cases
List all cases for the authenticated user.

### POST /api/v1/cases
Create a new legal case.

## Document Analysis Endpoints

### POST /api/v1/analyze/document
Initiate an asynchronous document analysis.

### GET /api/v1/analyze/{job_id}
Get the status of an analysis job.
